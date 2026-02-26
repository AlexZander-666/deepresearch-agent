from dotenv import load_dotenv
from utils.logger import logger
from utils.config import config
from utils.config import Configuration
import os
import json
# PPIO 沙箱 SDK - 根据类型动态导入

load_dotenv(override=True)

logger.debug("Initializing PPIP/E2B sandbox configuration")

# PPIO/E2B 配置 - 根据 PPIO 文档要求:https://ppio.com/docs/sandbox/get-start
# 设置 PPIO 沙箱域名
os.environ['E2B_DOMAIN'] = getattr(config, 'E2B_DOMAIN', 'sandbox.ppio.cn')

# 设置 E2B API Key
if hasattr(config, 'E2B_API_KEY') and config.E2B_API_KEY:
    os.environ['E2B_API_KEY'] = config.E2B_API_KEY
    logger.debug("E2B API key configured successfully")
elif 'E2B_API_KEY' in os.environ:
    logger.debug("E2B API key found in environment variables")
else:
    logger.warning("No E2B API key found in environment variables")

logger.debug(f"PPIO E2B Domain set to: {os.environ.get('E2B_DOMAIN')}")
logger.debug(f"E2B API Key configured: {'Yes' if os.environ.get('E2B_API_KEY') else 'No'}")

async def get_or_start_sandbox(sandbox_id: str, sandbox_type: str = 'desktop'):
    """Retrieve a sandbox by ID, check its state, and start it if needed."""
    
    logger.info(f"Getting or starting {sandbox_type} sandbox with ID: {sandbox_id}")

    try:
        # 根据沙箱类型选择合适的 SDK
        if sandbox_type == 'desktop':
            try:
                from e2b_desktop import Sandbox  # type: ignore
            except ImportError:
                raise ImportError("e2b-desktop not installed. Run: pip install e2b-desktop")
        elif sandbox_type == 'browser':
            try:
                from e2b_code_interpreter import Sandbox  # type: ignore
            except ImportError:
                raise ImportError("e2b-code-interpreter not installed. Run: pip install e2b-code-interpreter")
        elif sandbox_type in ['code', 'base']:
            try:
                from ppio_sandbox.code_interpreter import Sandbox  # type: ignore
            except ImportError:
                raise ImportError("ppio-sandbox not installed. Run: pip install ppio-sandbox")
        else:
            raise ValueError(f"Unsupported sandbox_type: {sandbox_type}")
            
        # 创建沙箱实例（不连接到现有沙箱）
        # 由于连接现有沙箱会有proxy参数问题，我们直接使用沙箱ID创建新实例
        try:
            # 检查构造函数的参数
            import inspect
            sig = inspect.signature(Sandbox.__init__)
            params = list(sig.parameters.keys())
            
            # 尝试不同的构造方式
            if 'sandbox_id' in params:
                sandbox = Sandbox(sandbox_id=sandbox_id)
            elif 'id' in params:
                sandbox = Sandbox(id=sandbox_id)
            else:
                # 最后尝试默认构造函数
                sandbox = Sandbox()
                # 尝试设置sandbox_id属性
                if hasattr(sandbox, 'sandbox_id'):
                    sandbox.sandbox_id = sandbox_id
                elif hasattr(sandbox, 'id'):
                    sandbox.id = sandbox_id
            
        except Exception as create_error:
            logger.warning(f"Failed to create sandbox instance {sandbox_id}: {create_error}")
            logger.warning(f"Creation error type: {type(create_error).__name__}")
            logger.warning(f"Creation error details: {str(create_error)}")
            raise Exception(f"Sandbox {sandbox_id} could not be instantiated")
        
        logger.info(f"Sandbox {sandbox_id} is ready")
        return sandbox
        
    except Exception as e:
        logger.error(f"Error retrieving or starting sandbox: {str(e)}")
        raise e

async def start_supervisord_session(sandbox):
    """Start supervisord in a session."""
    session_id = "supervisord-session"
    try:
        logger.info(f"Creating session {session_id} for supervisord")
        
        # 在 PPIO/E2B 中使用 commands.run 执行命令
        # 首先检查 supervisord 是否已经运行
        check_result = sandbox.commands.run("pgrep supervisord || echo 'not_running'")
        
        if 'not_running' in check_result.stdout:
            # 启动 supervisord
            sandbox.commands.run(
                "exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf &"
            )
            logger.info(f"Supervisord started in session {session_id}")
        else:
            logger.info("Supervisord is already running")
            
    except Exception as e:
        logger.error(f"Error starting supervisord session: {str(e)}")
        raise e

async def create_sandbox(password: str, project_id: str = None, sandbox_type: str = 'desktop'):
    """
    Create a new sandbox with all required services configured and running.
    
    Args:
        password: VNC 密码
        project_id: 项目ID  
        sandbox_type: 沙箱类型 ('desktop', 'browser', 'code', 'base')
    """
    
    # https://ppio.com/docs/sandbox/e2b-sandbox
    logger.debug(f"Creating new PPIP/E2B sandbox environment with type: {sandbox_type}")
    logger.debug("Configuring sandbox with template and environment variables")
    
    # 获取对应的模板ID
    template_id = config.get_sandbox_template(sandbox_type)
    logger.info(f"Using template: {template_id} for type: {sandbox_type}")
    
    # 准备元数据，用于沙箱管理和查询
    # PPIO E2B metadata 中所有值必须是字符串类型
    try:
        # 确保 sandbox_type 是字符串
        sandbox_type_str = str(sandbox_type) if sandbox_type else 'desktop'
        
        metadata = {
            # 基础信息
            'project_type': 'chrome_vnc',
            'created_by': 'agent_system',
            'version': '1.0',
            'sandbox_type': sandbox_type_str,
            }
        
        # Chrome/VNC 配置摘要 - 转换为 JSON 字符串
        try:
            chrome_config = {
                'persistent_session': True,
                'resolution': '1024x768x24', 
                'debugging_port': '9222',
                'vnc_enabled': True
            }
            metadata['chrome_config'] = json.dumps(chrome_config)
        except Exception as chrome_error:
            metadata['chrome_config'] = '{}'
        
        # 资源配置 - 转换为 JSON 字符串
        try:
            resources_config = {
                'cpu': 2,
                'memory': 4,
                'disk': 5
            }
            metadata['resources'] = json.dumps(resources_config)
        except Exception as resources_error:
            metadata['resources'] = '{}'
        
        # 标签 - 转换为逗号分隔的字符串
        try:
            tag_list = ['chrome', 'vnc', 'agent_sandbox', sandbox_type_str]
            metadata['tags'] = ','.join(tag_list)
        except Exception as tags_error:
            metadata['tags'] = 'chrome,vnc,agent_sandbox'
        
        if project_id:
            metadata['project_id'] = str(project_id)
                    
    except Exception as metadata_error:
        logger.error(f"sandbox_type: {sandbox_type} (type: {type(sandbox_type)})")
        logger.error(f"project_id: {project_id} (type: {type(project_id) if project_id else None})")
        raise
        
    # 创建沙盒 - PPIO 使用正确的关键字参数
    logger.info(f"Creating sandbox with template: {template_id}")
    
    # 根据沙箱类型选择合适的 SDK 和创建方式
    logger.info(f"Creating {sandbox_type} sandbox with template: {template_id}")
    
    if sandbox_type == 'desktop':
        # Computer Use - 使用 e2b-desktop
        try:
            from e2b_desktop import Sandbox  # type: ignore
            logger.debug("Successfully imported e2b_desktop.Sandbox")
        except ImportError as e:
            logger.error(f"Failed to import e2b-desktop: {e}")
            raise ImportError("e2b-desktop not installed. Run: pip install e2b-desktop")
        
        try:
            logger.info(f"Creating desktop sandbox with:")
            logger.info(f"  template={template_id} (type: {type(template_id)})")
            logger.info(f"  timeout=900")
            logger.info(f"  metadata keys={list(metadata.keys())}")
            logger.debug(f"  metadata content={metadata}")
            
            # 验证所有参数类型
            if not isinstance(template_id, str):
                raise TypeError(f"template_id must be string, got {type(template_id)}: {template_id}")
            
            for key, value in metadata.items():
                if not isinstance(key, str):
                    raise TypeError(f"metadata key must be string, got {type(key)}: {key}")
                if not isinstance(value, str):
                    raise TypeError(f"metadata[{key}] must be string, got {type(value)}: {value}")
            
            # 创建沙箱
            sandbox = Sandbox(
                template=template_id,           # 使用动态模板ID
                timeout=15 * 60,                # 使用 timeout 参数（秒为单位）
                metadata=metadata               # 直接传递 metadata
            )
            logger.info(f"Desktop sandbox created successfully")
            logger.info(f"Sandbox object type: {type(sandbox)}")
            logger.info(f"Sandbox ID: {sandbox.sandbox_id if hasattr(sandbox, 'sandbox_id') else 'no sandbox_id attribute'}")
            
            # 启动桌面流
            try:
                logger.info("Starting desktop stream for VNC access...")
                sandbox.stream.start()  # 同步方法，不需要 await
                logger.info("Desktop stream started successfully")

                url = sandbox.stream.get_url()  # 同步方法，不需要 await
                logger.info(f"Desktop stream URL: {url}")

                # 自动关闭 XFCE 通知区域警告弹窗并禁用通知插件
                try:
                    logger.info("Fixing XFCE notification area issue...")
                    import asyncio
                    await asyncio.sleep(3)  # 等待桌面完全加载

                    # 方法1: 直接关闭当前弹窗
                    sandbox.commands.run(
                        "DISPLAY=:99 xdotool search --name 'notification' windowactivate --sync key Escape 2>/dev/null || "
                        "DISPLAY=:99 xdotool search --class 'xfce4-notifyd' key Escape 2>/dev/null || "
                        "DISPLAY=:99 wmctrl -c 'notification' 2>/dev/null || "
                        "echo 'dialog closed or not found'"
                    )

                    # 方法2: 永久禁用 XFCE 通知插件（治本）
                    sandbox.commands.run(
                        "xfconf-query -c xfce4-panel -p /plugins/plugin-6 -s '' 2>/dev/null || "
                        "killall xfce4-notifyd 2>/dev/null || "
                        "true"
                    )

                    logger.info("XFCE notification area issue fixed")
                except Exception as close_error:
                    logger.debug(f"Could not fix notification dialog: {close_error}")
                    # 忽略错误，这只是用户体验优化

            except Exception as stream_error:
                logger.warning(f"Failed to start desktop stream: {stream_error}")
                # 不阻止沙箱创建，可能在后续获取链接时再试
            
        except Exception as e:
            logger.error(f"Failed to create desktop sandbox: {e}")
            logger.error(f"Exception type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    elif sandbox_type == 'browser':
        # Browser Use - 使用 e2b-code-interpreter
        try:
            from e2b_code_interpreter import Sandbox  # type: ignore
        except ImportError:
            raise ImportError("e2b-code-interpreter not installed. Run: pip install e2b-code-interpreter")
            
        sandbox = Sandbox(
            template=template_id,           # 使用动态模板ID
            timeout=15 * 60,                # 使用 timeout 参数（秒为单位）
            metadata=metadata               # 直接传递 metadata
        )
        try:
            logger.info("Verifying Chrome debugging protocol availability...")
            # 验证 9223 端口是否可用 (Chrome 调试协议端口)
            chrome_host = sandbox.get_host(9223)
            cdp_url = f"https://{chrome_host}"
            logger.info(f"Chrome debugging protocol address available: {cdp_url}")
    
            # 可以添加更多浏览器相关的验证
            logger.info("Browser sandbox initialized successfully")
            
        except Exception as e:
            logger.warning(f"Browser sandbox initialization warning: {e}")
            # 不阻止沙箱创建，浏览器可能需要一些时间启动
            
    elif sandbox_type in ['code', 'base']:
        # 普通沙箱 - 使用 ppio-sandbox
        try:
            from ppio_sandbox.code_interpreter import Sandbox  # type: ignore
        except ImportError:
            raise ImportError("ppio-sandbox not installed. Run: pip install ppio-sandbox")
            
        sandbox = Sandbox(
            template=template_id,           # 使用动态模板ID
            timeout=15 * 60,                # 使用 timeout 参数（秒为单位）
            metadata=metadata               # 直接传递 metadata
        )
        logger.info("Base/Code sandbox initialized successfully")
        
    else:
        raise ValueError(f"Unsupported sandbox_type: {sandbox_type}. Supported types: desktop, browser, code, base")
    
    # 设置环境变量
    try:
        await setup_environment_variables(sandbox, password)
    except Exception as env_error:
            logger.warning(f"环境变量设置失败: {env_error}")
        # 继续执行，环境变量设置失败不应该阻止沙箱创建
    
    # 启动 supervisord
    try:
        await start_supervisord_session(sandbox)
    except Exception as supervisord_error:
        logger.warning(f"Supervisord start failed: {supervisord_error}")
        # 继续执行，supervisord 启动失败不应该阻止沙箱创建
    
    logger.debug(f"Sandbox environment successfully initialized")
    return sandbox

async def setup_environment_variables(sandbox, password: str):
    """设置沙箱环境变量"""
    logger.debug("Setting up environment variables")
    
    # 环境变量配置
    env_vars = {
        "CHROME_PERSISTENT_SESSION": "true", # Chrome 持久化会话配置：开启
        "RESOLUTION": "1024x768x24",  # VNC 远程桌面配置：完整分辨率（宽高像素）
        "RESOLUTION_WIDTH": "1024",  # VNC 远程桌面配置：宽度像素
        "RESOLUTION_HEIGHT": "768",  # VNC 远程桌面配置：高度像素
        "VNC_PASSWORD": password,  # VNC 远程桌面配置：密码
        "ANONYMIZED_TELEMETRY": "false",  # 匿名化遥测配置：关闭
        "CHROME_PATH": "",  # Chrome 路径
        "CHROME_USER_DATA": "",  # Chrome 用户数据路径
        "CHROME_DEBUGGING_PORT": "9222",  # Chrome 调试端口
        "CHROME_DEBUGGING_HOST": "localhost",  # Chrome 调试主机
        "CHROME_CDP": ""  # Chrome CDP 配置

    }
    
    # 通过 commands.run 设置环境变量
    for key, value in env_vars.items():
        try:
            # 确保 key 和 value 都是字符串
            key_str = str(key)
            value_str = str(value) if value is not None else ""
            
            
            # 设置当前会话的环境变量
            export_cmd = f'export {key_str}="{value_str}"'
            sandbox.commands.run(export_cmd)
            
            # 添加到 .bashrc 以持久化
            bashrc_cmd = f'echo \'export {key_str}="{value_str}"\' >> ~/.bashrc'
            sandbox.commands.run(bashrc_cmd)

            
        except Exception as e:
            logger.warning(f"Failed to set environment variable {key}: {e}")
            logger.debug(f"Key type: {type(key)}, Value type: {type(value)}")
            logger.debug(f"Key: {key}, Value: {value}")
    
    # 重新加载 .bashrc
    try:
        sandbox.commands.run('source ~/.bashrc')
        logger.debug("Environment variables configured successfully")
    except Exception as e:
        logger.warning(f"Failed to reload .bashrc: {e}")

async def delete_sandbox(sandbox_id: str):
    """Delete a sandbox by its ID."""
    logger.info(f"Deleting sandbox with ID: {sandbox_id}")

    # 尝试不同的 SDK，因为不知道具体类型
    sdks_to_try = [
        ('e2b_desktop', 'e2b-desktop'),
        ('e2b_code_interpreter', 'e2b-code-interpreter'), 
        ('ppio_sandbox.code_interpreter', 'ppio-sandbox')
    ]
    
    for sdk_module, sdk_name in sdks_to_try:
        try:
            logger.debug(f"Trying to delete sandbox {sandbox_id} using {sdk_name}")
            
            # 动态导入对应的 SDK
            if sdk_module == 'e2b_desktop':
                from e2b_desktop import Sandbox  # type: ignore
            elif sdk_module == 'e2b_code_interpreter':
                from e2b_code_interpreter import Sandbox  # type: ignore
            elif sdk_module == 'ppio_sandbox.code_interpreter':
                from ppio_sandbox.code_interpreter import Sandbox  # type: ignore
                                
            # 尝试连接并删除
            sandbox = Sandbox(sandbox_id)
            sandbox.kill()  # 同步方法，不需要 await
            
            logger.info(f"Successfully deleted sandbox {sandbox_id} using {sdk_name}")
            return True
        
        except ImportError:
            logger.debug(f"SDK {sdk_name} not available, skipping")
            continue
        except Exception as e:
            logger.debug(f"Failed to delete sandbox {sandbox_id} using {sdk_name}: {e}")
            continue
    
    # 如果所有 SDK 都失败了
    raise Exception(f"Failed to delete sandbox {sandbox_id} with all available SDKs")

async def pause_sandbox(sandbox) -> str:
    """暂停沙箱（替代 Daytona 的归档功能）"""
    logger.info(f"Pausing sandbox {sandbox.sandboxId}")
    
    try:
        # 暂停沙箱
        sandbox_id = await sandbox.pause()
        logger.info(f"Successfully paused sandbox {sandbox_id}")
        return sandbox_id
    except Exception as e:
        logger.error(f"Error pausing sandbox: {e}")
        raise e

async def get_sandbox_metrics(sandbox):
    """获取沙箱资源使用指标"""
    try:
        metrics = await sandbox.getMetrics()
        logger.debug(f"Sandbox metrics: {metrics}")
        return metrics
    except Exception as e:
        logger.warning(f"Failed to get sandbox metrics: {e}")
        return None

async def list_sandboxes(metadata_filter: dict = None):
    """列出所有沙箱 - PPIO 暂不支持复杂查询，返回空列表"""
    try:
        # PPIO 的 E2B SDK 可能不支持复杂的列表查询
        # 这里返回空列表，实际使用中可能需要其他方式管理沙箱列表
        logger.warning("PPIO sandbox listing not fully supported, returning empty list")
        return []
    except Exception as e:
        logger.error(f"Error listing sandboxes: {e}")
        return []

# 元数据的实际使用示例
async def find_chrome_sandboxes():
    """查找所有 Chrome 类型的沙箱"""
    return await list_sandboxes({'project_type': 'chrome_vnc'})

async def find_project_sandboxes(project_id: str):
    """查找特定项目的沙箱"""
    return await list_sandboxes({'project_id': project_id})

async def find_agent_sandboxes():
    """查找所有 agent 创建的沙箱"""
    return await list_sandboxes({'created_by': 'agent_system'})

async def get_sandbox_config_summary(sandbox):
    """从元数据快速获取配置摘要"""
    try:
        info = await sandbox.getInfo()
        metadata = info.get('metadata', {})
        
        return {
            'type': metadata.get('project_type', 'unknown'),
            'chrome_config': metadata.get('chrome_config', {}),
            'resources': metadata.get('resources', {}),
            'tags': metadata.get('tags', [])
        }
    except Exception as e:
        logger.warning(f"Failed to get config summary: {e}")
        return None
