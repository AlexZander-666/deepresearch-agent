import dotenv
dotenv.load_dotenv(".env")


import sentry
import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Optional
from services import redis
from agent.run import run_agent
from utils.logger import logger, structlog
import dramatiq # type: ignore
import uuid
from agentpress.thread_manager import ThreadManager
from services.postgresql import DBConnection
from services import redis
from dramatiq.brokers.redis import RedisBroker # type: ignore
import os
from services.langfuse import langfuse
from utils.retry import retry

import sentry_sdk # type: ignore
from typing import Dict, Any

# 使用与 services/redis.py 相同的配置
redis_host = os.getenv('REDIS_HOST', 'redis')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_password = os.getenv('REDIS_PASSWORD', '')
redis_db = int(os.getenv('REDIS_DB', 0))

# 创建Redis broker，使用与 services/redis.py 相同的配置
if redis_password:
    redis_broker = RedisBroker(
        host=redis_host, 
        port=redis_port, 
        password=redis_password,
        db=redis_db,
        middleware=[dramatiq.middleware.AsyncIO()]
    )
else:
    redis_broker = RedisBroker(
        host=redis_host, 
        port=redis_port, 
        db=redis_db,
        middleware=[dramatiq.middleware.AsyncIO()]
    )

dramatiq.set_broker(redis_broker)

_initialized = False
db = DBConnection()
instance_id = "single"

async def initialize():
    """Initialize the agent API with resources from the main API."""
    global db, instance_id, _initialized

    if not instance_id:
        instance_id = str(uuid.uuid4())[:8]
    await retry(lambda: redis.initialize_async())
    await db.initialize()

    _initialized = True
    logger.info(f"Initialized agent API with instance ID: {instance_id}")

@dramatiq.actor
async def check_health(key: str):
    """Run the agent in the background using Redis for state."""
    structlog.contextvars.clear_contextvars()
    await redis.set(key, "healthy", ex=redis.REDIS_KEY_TTL)


"""
Redis:内存数据库，做键值存储 + 发布订阅，项目中的角色定位是：数据存储 + 通信枢纽
Dramatiq:任务队列，做异步任务调度，项目中的角色定位是：后台任务管理器

@dramatiq.actor：将普通函数转换为可调度的后台任务， 自动添加 .send() 方法，让函数可以被Dramatiq worker执行
"""
@dramatiq.actor
async def run_agent_background(
    agent_run_id: str,
    thread_id: str,
    instance_id: str, 
    project_id: str,
    model_name: str,
    enable_thinking: Optional[bool],
    reasoning_effort: Optional[str],
    stream: bool,
    enable_context_manager: bool,
    agent_config: Optional[dict] = None,
    is_agent_builder: Optional[bool] = False,
    target_agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Run the agent in the background using Redis for state."""
    # 并发场景下：管理结构化日志的上下文变量，确保每个Agent运行任务有独立、干净的日志上下文
    # 先清除所有上下文变量
    structlog.contextvars.clear_contextvars()
    # 再绑定新的上下文变量（当前运行）
    # 为当前任务绑定新的上下文变量
    # 效果: 后续所有日志都会自动包含这些字段
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
        thread_id=thread_id,
        request_id=request_id,
    )
    try:
        # 初始化 Redis 和 Postgresql 连接实例
        await initialize()
        logger.info(f"Initialized Redis and Postgresql connection successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis connection: {e}")
        raise e

    # 锁机制确保只有一个实例处理同一个agent_run_id
    # 避免重复执行和资源浪费
    run_lock_key = f"agent_run_lock:{agent_run_id}"
    
    # 获取运行锁
    # 多个后端实例同时运行
    # Instance-A: 尝试处理 agent_run_123
    # Instance-B: 也尝试处理 agent_run_123  拒绝：被锁阻止
    # Instance-C: 也尝试处理 agent_run_123  拒绝：被锁阻止
    # 只有Instance-A成功获取锁，继续执行
    # 其他实例被阻塞，直到锁释放
    # 锁释放后，其他实例可以重新尝试获取锁
    try:
        # TTL = 过期时间：设置锁时同时设置过期时间
        # # 一般设置
        # REDIS_KEY_TTL = 3600  # 1小时
        # REDIS_KEY_TTL = 1800  # 30分钟  
        # REDIS_KEY_TTL = 600   # 10分钟 (短任务)

        # 平衡考虑
        # 太短: 长任务还没完成锁就过期了 → 重复执行
        # 太长: 崩溃后等待时间太久 → 影响恢复速度 
        lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
        logger.info(f"Redis SET command completed: {lock_acquired}")
    except Exception as redis_error:
        logger.error(f"Redis lock operation failed, Error details: {traceback.format_exc()}")
        raise redis_error
    
    # Redis分布式锁机制
    #   ↓
    # 第一次尝试获取锁 (nx=True)
    #   ↓
    # ├─成功 → 继续执行Agent
    # ├─失败 → 检查现有实例
    #   ↓
    #   ├─有实例值 → 退出 (避免重复)
    #   ├─无实例值 → 第二次尝试获取
    #           ↓
    #           ├─成功 → 继续执行Agent  
    #           ├─失败 → 退出 (其他实例抢到了)
    if not lock_acquired:
        # 检查是否已有其他实例在处理
        try:
            existing_instance = await redis.get(run_lock_key)
            logger.info(f"Existing instance: {existing_instance}")
        except Exception as redis_error:
            logger.error(f"Redis GET operation failed, Error details: {traceback.format_exc()}")
            raise redis_error
        if existing_instance:
            # 已有实例在处理，把 existing_instance 转换为字符串，做一个日志记录
            existing_instance_str = existing_instance.decode() if isinstance(existing_instance, bytes) else existing_instance
            logger.warning(f"Agent run {agent_run_id} is already being processed by instance {existing_instance_str}. Skipping duplicate execution.")
            return
        else:
            # 锁存在但无值，再次尝试获取
            # 第二次获取锁的意义 - 处理竞态条件
            # 时间线分析：
            # 1. Instance-A的锁即将过期 (TTL=1秒后过期)
            # 2. Instance-B尝试获取锁
            # 3. redis.set(nx=True) → 失败  (因为key还存在)
            # 4. Redis自动清理过期的key 
            # 5. redis.get() → None (key已被清理)
            # 6. 第二次尝试 redis.set(nx=True) → 成功 
            try:
                lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
            except Exception as redis_error:
                logger.error(f"Redis second lock operation failed, Error details: {traceback.format_exc()}")
                raise redis_error
            if not lock_acquired:
                logger.warning(f"Agent run {agent_run_id} is already being processed by another instance. Skipping duplicate execution.")
                return
    else:
        logger.info(f"Successfully acquired run lock")

    try:
        # Sentry 是一个 应用监控和错误追踪平台，主要用于帮助开发者 实时发现、定位和分析应用中的错误和性能问题
        # Docs：https://docs.sentry.io/platforms/python/
        sentry.sentry.set_tag("thread_id", thread_id)
        logger.info(f"Sentry tag setting completed")
    except Exception as sentry_error:
        logger.error(f"Sentry tag setting failed, Error details: {sentry_error}")


    # 使用已解析的模型名
    effective_model = model_name  # 现在传入的已经是解析后的最终模型名

    try:
        client = await db.client
        logger.info(f"Database client acquisition successful")
    except Exception as db_error:
        logger.error(f"Database client acquisition failed, Error details: {db_error}")
        raise db_error
    
    # 初始化时间、响应计数、Pub/Sub、停止信号检查器、待处理Redis操作
    start_time = datetime.now(timezone.utc)
    total_responses = 0
    pubsub = None
    stop_checker = None
    stop_signal_received = False
    pending_redis_operations = []  

    # 定义 Redis keys 和 channels
    # 两层控制架构
    response_list_key = f"agent_run:{agent_run_id}:responses" 
    response_channel = f"agent_run:{agent_run_id}:new_response"
    instance_control_channel = f"agent_run:{agent_run_id}:control:{instance_id}" # 精确控制
    global_control_channel = f"agent_run:{agent_run_id}:control"  #  广播控制
    instance_active_key = f"active_run:{instance_id}:{agent_run_id}"
    
    # 用户在前端点击"停止"按钮
    # 前端 → 后端API → Redis发布 "STOP" 消息
    # → instance_control_channel 或 global_control_channel
    # → 正在运行的Agent接收到信号 → 立即停止执行

    async def check_for_stop_signal():
        """
        实时监听Redis中的STOP信号
        """
        nonlocal stop_signal_received

        if not pubsub: 
            logger.warning(f"PubSub not initialized, exiting checker")
            return
        try:
            while not stop_signal_received:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, bytes): data = data.decode('utf-8')
                    if data == "STOP":
                        logger.info(f"Received STOP signal for agent run {agent_run_id} (Instance: {instance_id})")
                        stop_signal_received = True
                        break
                # 持久化刷新活跃运行键的TTL
                if total_responses % 50 == 0: # 每50个响应刷新一次
                    try: 
                        await redis.expire(instance_active_key, redis.REDIS_KEY_TTL)
                        logger.info(f"TTL refreshed (response count: {total_responses})")
                    except Exception as ttl_err: 
                        logger.warning(f"Failed to refresh TTL for {instance_active_key}: {ttl_err}")
                await asyncio.sleep(0.1) # Short sleep to prevent tight loop
        except asyncio.CancelledError:
            logger.info(f"Stop signal checker cancelled for {agent_run_id} (Instance: {instance_id})")
        except Exception as e:
            logger.error(f"Error in stop signal checker for {agent_run_id}: {e}", exc_info=True)
            stop_signal_received = True # Stop the run if the checker fails

    # 创建 Langfuse 跟踪
    trace = langfuse.trace(name="agent_run", id=agent_run_id, session_id=thread_id, metadata={"project_id": project_id, "instance_id": instance_id})
    logger.info(f"Langfuse trace created successfully")
    
    try:
        # 处理前端终止操作
        # 前端用户: 点击"停止Agent"按钮 
        #          ↓
        # 后端API: 接收停止请求
        #          ↓  
        # Redis: 发布"STOP"信号到control_channel
        #          ↓
        # 后端Agent: 订阅并接收到"STOP"信号
        #          ↓
        # Agent: 优雅停止执行，清理资源 

        # 创建 Pub/Sub 连接
        pubsub = await redis.create_pubsub()
        logger.info(f"PubSub connection created successfully")
        try:
            # 订阅控制频道
            await retry(lambda: pubsub.subscribe(instance_control_channel, global_control_channel))
            logger.info(f"Control channels subscribed successfully")
        except Exception as e:
            logger.error(f"Redis failed to subscribe to control channels: {e}", exc_info=True)
            raise e

        logger.debug(f"Subscribed to control channels: {instance_control_channel}, {global_control_channel}")
        stop_checker = asyncio.create_task(check_for_stop_signal())
        logger.info(f"Stop signal checker started successfully")
        # 确保活跃运行键存在并设置TTL
        await redis.set(instance_active_key, "running", ex=redis.REDIS_KEY_TTL)
        logger.info(f"Active run key set successfully")

        # 初始化Agent生成器
        try:
            # 这里开始执行Agent的逻辑。注意：这里仅仅是创建生成器，并不执行
            agent_gen = run_agent(
                thread_id=thread_id, 
                project_id=project_id, 
                stream=stream,
                native_max_auto_continues=0,  
                model_name=effective_model,
                enable_thinking=enable_thinking, 
                reasoning_effort=reasoning_effort,
                enable_context_manager=enable_context_manager,
                agent_config=agent_config,
                trace=trace,
                is_agent_builder=is_agent_builder,
                target_agent_id=target_agent_id,
            )
            logger.info(f"Agent run {agent_run_id} started successfully")
            
        except Exception as agent_error:
            logger.error(f"Failed to call run_agent: {agent_error}")
            raise agent_error

        final_status = "running"
        error_message = None
        pending_redis_operations = []

        response_count = 0

        # 从这里开始真正执行：runner.run()
        async for response in agent_gen:
            response_count += 1
            # 检查是否收到STOP信号
            if stop_signal_received:
                logger.info(f"Agent run {agent_run_id} stopped by signal.")
                final_status = "stopped"
                try:
                    trace.span(name="agent_run_stopped").end(status_message="agent_run_stopped", level="WARNING")
                except Exception as trace_error:
                    logger.warning(f"Failed to record trace for agent run {agent_run_id}: {trace_error}")
                break

            # 存储响应到Redis列表并发布通知
            response_json = json.dumps(response)
            # Redis List 就像一个双端队列
            # [左端/头部] ← 元素1 - 元素2 - 元素3 → [右端/尾部]
            #    ↑                                    ↑
            # lpush                               rpush
            # (左入栈)                            (右入栈)
            pending_redis_operations.append(asyncio.create_task(redis.rpush(response_list_key, response_json)))
            pending_redis_operations.append(asyncio.create_task(redis.publish(response_channel, "new")))
            total_responses += 1
            
            if total_responses % 10 == 1:  # 每10个响应打印一次进度
                logger.info(f"Agent run {agent_run_id} has processed {total_responses} responses")

            # 检查是否收到Agent信号完成或错误
            if response.get('type') == 'status':
                 status_val = response.get('status')
                 if status_val in ['completed', 'failed', 'stopped']:
                     logger.info(f"Agent run {agent_run_id} finished via status message: {status_val}")
                     final_status = status_val
                     if status_val == 'failed' or status_val == 'stopped':
                         error_message = response.get('message', f"Run ended with status: {status_val}")
                     break

        # 如果循环结束没有显式完成/错误/停止信号，标记为完成
        if final_status == "running":
             final_status = "completed"
             duration = (datetime.now(timezone.utc) - start_time).total_seconds()
             logger.info(f"Agent run {agent_run_id} completed normally (duration: {duration:.2f}s, responses: {total_responses})")
             completion_message = {"type": "status", "status": "completed", "message": "Agent run completed successfully"}
             trace.span(name="agent_run_completed").end(status_message="agent_run_completed")
             await redis.rpush(response_list_key, json.dumps(completion_message))
             await redis.publish(response_channel, "new") # 发布完成消息

        # 从Redis获取最终响应用于更新数据库状态
        all_responses_json = await redis.lrange(response_list_key, 0, -1)

        # 更新数据库状态
        await update_agent_run_status(client, agent_run_id, final_status, error=error_message)

        # 发布最终控制信号 (END_STREAM or ERROR)
        control_signal = "END_STREAM" if final_status == "completed" else "ERROR" if final_status == "failed" else "STOP"
        
        try:
            await redis.publish(global_control_channel, control_signal)
            # 不需要发布到实例频道，因为运行正在这个实例上结束
            logger.debug(f"Published final control signal '{control_signal}' to {global_control_channel}")
        except Exception as e:
            logger.warning(f"Failed to publish final control signal {control_signal}: {str(e)}")

    except Exception as e:
        # 捕获异常
        error_message = str(e)
        traceback_str = traceback.format_exc()
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.error(f"Error in agent run {agent_run_id} after {duration:.2f}s: {error_message}\n{traceback_str} (Instance: {instance_id})")
        final_status = "failed"
        try:
            trace.span(name="agent_run_failed").end(status_message=error_message, level="ERROR")
        except Exception as trace_error:
            logger.warning(f"Trace failed: {trace_error}")

        # 将错误消息推送到Redis列表
        error_response = {"type": "status", "status": "error", "message": error_message}
        try:
            await redis.rpush(response_list_key, json.dumps(error_response))
            await redis.publish(response_channel, "new")
        except Exception as redis_err:
             logger.error(f"Failed to push error response to Redis for {agent_run_id}: {redis_err}")

        # 从Redis获取最终响应用于更新数据库状态
        try:
             all_responses_json = await redis.lrange(response_list_key, 0, -1)
             logger.info(f"Fetched {len(all_responses_json)} responses from Redis for {agent_run_id}")
        except Exception as fetch_err:
             logger.error(f"Failed to fetch responses from Redis after error for {agent_run_id}: {fetch_err}")

        # 更新数据库状态
        await update_agent_run_status(client, agent_run_id, "failed", error=f"{error_message}\n{traceback_str}")

        # 发布ERROR信号
        try:
            await redis.publish(global_control_channel, "ERROR")
            logger.debug(f"Published ERROR signal to {global_control_channel}")
        except Exception as e:
            logger.warning(f"Failed to publish ERROR signal: {str(e)}")
    finally:
        # 清理停止检查器任务
        if stop_checker and not stop_checker.done():
            stop_checker.cancel()
            try: 
                await stop_checker
            except asyncio.CancelledError: 
                pass
            except Exception as e: 
                logger.warning(f"Error during stop_checker cancellation: {e}")

        # 关闭pubsub连接
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
                logger.debug(f"Closed pubsub connection for {agent_run_id}")
            except Exception as e:
                logger.warning(f"Error closing pubsub for {agent_run_id}: {str(e)}")

        # 设置Redis响应列表的TTL
        await _cleanup_redis_response_list(agent_run_id)
 

        # 清理实例特定的活跃运行键
        await _cleanup_redis_instance_key(agent_run_id)
   

        # 清理运行锁
        await _cleanup_redis_run_lock(agent_run_id)

        # 等待所有挂起的Redis操作完成，超时30秒
        try:
            await asyncio.wait_for(asyncio.gather(*pending_redis_operations), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for pending Redis operations for {agent_run_id}")

        logger.info(f"Agent run background task fully completed for: {agent_run_id} (Instance: {instance_id}) with final status: {final_status}")

async def _cleanup_redis_instance_key(agent_run_id: str):
    """Clean up the instance-specific Redis key for an agent run."""
    if not instance_id:
        logger.warning("Instance ID not set, cannot clean up instance key.")
        return
    key = f"active_run:{instance_id}:{agent_run_id}"
    logger.debug(f"Cleaning up Redis instance key: {key}")
    try:
        await redis.delete(key)
        logger.debug(f"Successfully cleaned up Redis key: {key}")
    except Exception as e:
        logger.warning(f"Failed to clean up Redis key {key}: {str(e)}")

async def _cleanup_redis_run_lock(agent_run_id: str):
    """Clean up the run lock Redis key for an agent run."""
    run_lock_key = f"agent_run_lock:{agent_run_id}"
    logger.debug(f"Cleaning up Redis run lock key: {run_lock_key}")
    try:
        await redis.delete(run_lock_key)
        logger.debug(f"Successfully cleaned up Redis run lock key: {run_lock_key}")
    except Exception as e:
        logger.warning(f"Failed to clean up Redis run lock key {run_lock_key}: {str(e)}")

# TTL for Redis response lists (24 hours)
REDIS_RESPONSE_LIST_TTL = 3600 * 24

async def _cleanup_redis_response_list(agent_run_id: str):
    """Set TTL on the Redis response list."""
    response_list_key = f"agent_run:{agent_run_id}:responses"
    try:
        # 销毁Redis响应列表
        await redis.expire(response_list_key, REDIS_RESPONSE_LIST_TTL)
        logger.debug(f"Set TTL ({REDIS_RESPONSE_LIST_TTL}s) on response list: {response_list_key}")
    except Exception as e:
        logger.warning(f"Failed to set TTL on response list {response_list_key}: {str(e)}")

async def update_agent_run_status(
    client,
    agent_run_id: str,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """
    Centralized function to update agent run status.
    Returns True if update was successful.
    """
    try:
        update_data = {
            "status": status,
            "completed_at": datetime.now(timezone.utc)  # 直接传递 datetime 对象，而不是字符串
        }

        if error:
            # 确保error是字符串
            if isinstance(error, list):
                error = str(error)
            elif not isinstance(error, str):
                error = str(error)
            update_data["error"] = error

        # 重试3次
        for retry in range(3):
            try:
                # 确保 client 是已初始化的数据库客户端
                if hasattr(client, 'table'):
                    # 更新数据库状态
                    update_result = await client.table('agent_runs').eq("agent_run_id", agent_run_id).update(update_data)
                else:
                    # 如果 client 不是数据库客户端，尝试获取数据库连接
                    from services.postgresql import DBConnection
                    db_conn = DBConnection()
                    db_client = await db_conn.client
                    update_result = await db_client.table('agent_runs').eq("agent_run_id", agent_run_id).update(update_data)
                if hasattr(update_result, 'data') and update_result.data:
                    logger.info(f"Successfully updated agent run {agent_run_id} status to '{status}' (retry {retry})")
                    return True
                else:
                    logger.warning(f"Database update returned no data for agent run {agent_run_id} on retry {retry}: {update_result}")
                    if retry == 2:  # Last retry
                        logger.error(f"Failed to update agent run status after all retries: {agent_run_id}")
                        return False
            except Exception as db_error:
                logger.error(f"Database error on retry {retry} updating status for {agent_run_id}: {str(db_error)}")
                if retry < 2:  # Not the last retry yet
                    await asyncio.sleep(0.5 * (2 ** retry))  # Exponential backoff
                else:
                    logger.error(f"Failed to update agent run status after all retries: {agent_run_id}", exc_info=True)
                    return False
    except Exception as e:
        logger.error(f"Unexpected error updating agent run status for {agent_run_id}: {str(e)}", exc_info=True)
        return False
    return False
