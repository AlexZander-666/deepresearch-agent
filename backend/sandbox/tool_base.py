from typing import Optional
import uuid

from agentpress.adk_thread_manager import ADKThreadManager
from agentpress.tool import Tool
from typing import Any
# PPIO 沙箱类型 - 根据 sandbox_type 在 create_sandbox 中动态选择具体实现
# 支持: desktop (e2b-desktop), browser (e2b-code-interpreter), base (ppio-sandbox)
from sandbox.sandbox import get_or_start_sandbox, create_sandbox, delete_sandbox
from utils.logger import logger
from utils.files_utils import clean_path

class SandboxToolsBase(Tool):
    """All sandbox tools base class, provide sandbox access based on project."""
    
    # 类变量，跟踪是否已打印沙箱URL
    _urls_printed = False
    
    def __init__(self, project_id: str, thread_manager: Optional[ADKThreadManager] = None, sandbox_type: str = 'desktop'):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.sandbox_type = sandbox_type  # 沙箱类型
        self.workspace_path = "/workspace"
        self._sandbox = None
        self._sandbox_id = None
        self._sandbox_pass = None

    async def _ensure_sandbox(self) -> Any:
        """Ensure a valid sandbox instance, retrieve it from the project if needed.

        If the project doesn't have a sandbox, lazily create it and persist the metadata to the `projects` table
        so subsequent calls can reuse it.
        """
        if self._sandbox is None:
            try:
                # 获取数据库客户端
                client = await self.thread_manager.db.client
            
                # 获取项目数据
                project = await client.table('projects').select('*').eq('project_id', self.project_id).execute()
                if not project.data or len(project.data) == 0:
                    raise ValueError(f"Project {self.project_id} not found")

                project_data = project.data[0]
                
                # 处理sandbox信息 - sandbox字段是JSON字符串
                raw_sandbox = project_data.get('sandbox', '{}')
                if isinstance(raw_sandbox, str):
                    try:
                        import json
                        sandbox_info = json.loads(raw_sandbox) if raw_sandbox.strip() else {}
                    except json.JSONDecodeError as e:
                        sandbox_info = {}
                elif isinstance(raw_sandbox, dict):
                    sandbox_info = raw_sandbox
                else:
                    sandbox_info = {}
                
                # 如果项目没有记录沙箱，懒加载创建一个
                if not sandbox_info.get('id'):
                    sandbox_pass = str(uuid.uuid4())
                    try:
                        sandbox_obj = await create_sandbox(sandbox_pass, self.project_id, self.sandbox_type)
                        sandbox_id = sandbox_obj.sandbox_id  # 使用 sandbox_id 属性
                    except Exception as create_error:
                        logger.error(f"sandbox create error: {create_error}")
                        logger.error(f"sandbox create error type: {type(create_error)}")
                        raise

                    # 处理桌面流 - 仅适用于 desktop 类型沙箱
                    try:
                        vnc_url = None
                        if self.sandbox_type == 'desktop':
                            try:
                                sandbox_obj.stream.start()
                            except Exception as start_error:
                                if "already running" in str(start_error).lower():
                                    logger.info("desktop stream already running, skip start step")
                                else:
                                    logger.error(f"desktop stream start error: {start_error}")
                                    raise start_error
                            
                            # 获取 VNC 地址（同步方法） - 无论 start() 是否成功都能调用
                            vnc_url_raw = sandbox_obj.stream.get_url()
                        else:
                            vnc_url_raw = None
                        
                        # 安全处理VNC URL - 确保是字符串
                        if isinstance(vnc_url_raw, list):
                            vnc_url = vnc_url_raw[0] if vnc_url_raw else ""
                        elif hasattr(vnc_url_raw, 'url'):
                            vnc_url = vnc_url_raw.url
                        else:
                            vnc_url = str(vnc_url_raw) if vnc_url_raw else ""
                        
                        # 对于网站URL，暂时设置为None或使用桌面流地址
                        website_url = vnc_url  # E2B Desktop 的主要交互地址
                        token = None           # PPIO E2B Desktop 不使用token方式
                        
                    except Exception as stream_error:
                        # 如果桌面流获取失败，仍继续但将字段设置为 None
                        import traceback
                        logger.error(f"desktop stream get url error: {traceback.format_exc()}")
                        vnc_url = None
                        website_url = None
                        token = None

                    # 持久化沙箱元数据到项目记录     
                    # 构建沙箱元数据（确保所有值都是字符串，用于JSONB存储）
                    # 安全处理所有字段，确保不会有字符串拼接错误
                    try:
                        safe_vnc_url = None
                        if vnc_url:
                            if isinstance(vnc_url, str):
                                safe_vnc_url = vnc_url
                            elif isinstance(vnc_url, list):
                                safe_vnc_url = vnc_url[0] if vnc_url else ""
                            else:
                                safe_vnc_url = str(vnc_url)
                        
                        safe_website_url = None
                        if website_url:
                            if isinstance(website_url, str):
                                safe_website_url = website_url
                            elif isinstance(website_url, list):
                                safe_website_url = website_url[0] if website_url else ""
                            else:
                                safe_website_url = str(website_url)
                        
                        sandbox_metadata = {
                            'id': str(sandbox_id),
                            'pass': str(sandbox_pass),
                            'type': str(self.sandbox_type),  # 保存沙箱类型
                            'vnc_preview': safe_vnc_url,
                            'sandbox_url': safe_website_url,
                            'token': str(token) if token else None
                        }

                    except Exception as metadata_error:
                        logger.error(f"sandbox metadata build error: {metadata_error}")
                        logger.error(f"sandbox metadata build error type: {type(metadata_error)}")
                        raise Exception(f"sandbox metadata build error: {metadata_error}")
                    
                    # PostgreSQL的JSONB字段需要JSON字符串
                    import json
                    update_data = {
                        'sandbox': json.dumps(sandbox_metadata)
                    }
                    
                    # 执行数据库更新 - 修正语法：先设置条件，再调用update
                    try:
                        project_table = client.table('projects').eq('project_id', self.project_id)
                        update_result = await project_table.update(update_data)
                    except Exception as update_error:
                        import traceback
                        logger.error(f"database update error: {traceback.format_exc()}")
                        raise

                    # 检查逻辑：空列表不等于失败
                    if update_result.data is None:
                        # 如果结果为None（而不是空列表），才认为是真正的失败
                        try:
                            await delete_sandbox(sandbox_id)
                        except Exception:
                            logger.error(f"Failed to delete sandbox {sandbox_id} after DB update failure", exc_info=True)
                        raise Exception("Database update failed when storing sandbox metadata")
                    elif isinstance(update_result.data, list) and len(update_result.data) == 0:
                        # 空列表意味着没有找到匹配的项目来更新
                        # 先检查项目是否存在
                        try:
                            project_check = await client.table('projects').select('project_id, name').eq('project_id', self.project_id).execute()
                        except Exception as check_error:
                            logger.error(f"project check error: {check_error}")
                        
                        # 清理沙箱
                        try:
                            await delete_sandbox(sandbox_id)
                        except Exception:
                            logger.error(f"Failed to delete sandbox {sandbox_id} after project not found", exc_info=True)
                        raise Exception(f"Project {self.project_id} not found for sandbox metadata update")
                    else:
                        logger.info(f"database update success, updated {len(update_result.data)} rows")

                    # 存储本地元数据，直接使用刚创建的沙箱对象
                    self._sandbox_id = sandbox_id
                    self._sandbox_pass = sandbox_pass
                    # 直接使用 sandbox_obj，避免重新连接的问题
                    self._sandbox = sandbox_obj
                else:
                    # 使用现有的沙箱元数据
                    self._sandbox_id = sandbox_info['id']
                    self._sandbox_pass = sandbox_info.get('pass')
                    existing_sandbox_type = sandbox_info.get('type', 'desktop')  # 从数据库获取类型
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id, existing_sandbox_type)

            except Exception as e:
                logger.error(f"Error retrieving/creating sandbox for project {self.project_id}: {str(e)}", exc_info=True)
                raise e

        return self._sandbox

    @property
    def sandbox(self) -> Any:
        """Get the sandbox instance, ensuring it exists."""
        if self._sandbox is None:
            raise RuntimeError("Sandbox not initialized. Call _ensure_sandbox() first.")
        return self._sandbox

    @property
    def sandbox_id(self) -> str:
        """Get the sandbox ID, ensuring it exists."""
        if self._sandbox_id is None:
            raise RuntimeError("Sandbox ID not initialized. Call _ensure_sandbox() first.")
        return self._sandbox_id

    def clean_path(self, path: str) -> str:
        """Clean and normalize a path to be relative to /workspace."""
        cleaned_path = clean_path(path, self.workspace_path)
        logger.debug(f"Cleaned path: {path} -> {cleaned_path}")
        return cleaned_path