"""
custom_agents = True       是否启用自定义Agent功能
mcp_module = True          是否启用MCP模块
templates_api = True       是否启用模板API
triggers_api = True        是否启用触发器API
workflows_api = True       是否启用工作流API
knowledge_base = True      是否启用知识库
pipedream = True           是否启用Pipedream集成
credentials_api = True     是否启用凭据API
default_agent = True       是否启用默认Agent
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import redis

logger = logging.getLogger(__name__)

class FeatureFlagManager:
    def __init__(self):
        """Initialize with existing Redis service"""
        self.flag_prefix = "feature_flag:"
        self.flag_list_key = "feature_flags:list"
    
    async def set_flag(self, key: str, enabled: bool, description: str = "") -> bool:
        """Set a feature flag to enabled or disabled"""
        try:
            flag_key = f"{self.flag_prefix}{key}"
            flag_data = {
                'enabled': str(enabled).lower(),
                'description': description,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            # Use the existing Redis service
            redis_client = await redis.get_client()
            await redis_client.hset(flag_key, mapping=flag_data)
            await redis_client.sadd(self.flag_list_key, key)
            
            logger.info(f"Set feature flag {key} to {enabled}")
            return True
        except Exception as e:
            logger.error(f"Failed to set feature flag {key}: {e}")
            return False
    
    async def is_enabled(self, key: str) -> bool:
        """Check if a feature flag is enabled"""
        try:
            flag_key = f"{self.flag_prefix}{key}"
            
            redis_client = await redis.get_client()
            
            enabled = await redis_client.hget(flag_key, 'enabled')
            
            result = enabled == 'true' if enabled else False
            return result
            
        except Exception as e:
            logger.error(f"❌ [FLAGS] Failed to check feature flag {key}: {e}")
            logger.error(f"❌ [FLAGS] Exception type: {type(e)}")
            import traceback
            logger.error(f"❌ [FLAGS] Traceback: {traceback.format_exc()}")
            # Return False by default if Redis is unavailable
            return False
    
    async def get_flag(self, key: str) -> Optional[Dict[str, str]]:
        """Get feature flag details"""
        try:
            flag_key = f"{self.flag_prefix}{key}"
            redis_client = await redis.get_client()
            flag_data = await redis_client.hgetall(flag_key)
            return flag_data if flag_data else None
        except Exception as e:
            logger.error(f"Failed to get feature flag {key}: {e}")
            return None
    
    async def delete_flag(self, key: str) -> bool:
        """Delete a feature flag"""
        try:
            flag_key = f"{self.flag_prefix}{key}"
            redis_client = await redis.get_client()
            deleted = await redis_client.delete(flag_key)
            if deleted:
                await redis_client.srem(self.flag_list_key, key)
                logger.info(f"Deleted feature flag: {key}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete feature flag {key}: {e}")
            return False
    
    async def list_flags(self) -> Dict[str, bool]:
        """List all feature flags with their status"""
        try:
            redis_client = await redis.get_client()
            flag_keys = await redis_client.smembers(self.flag_list_key)
            flags = {}
            
            for key in flag_keys:
                flags[key] = await self.is_enabled(key)
            
            return flags
        except Exception as e:
            logger.error(f"Failed to list feature flags: {e}")
            return {}
    
    async def get_all_flags_details(self) -> Dict[str, Dict[str, str]]:
        """Get all feature flags with detailed information"""
        try:
            redis_client = await redis.get_client()
            flag_keys = await redis_client.smembers(self.flag_list_key)
            flags = {}
            
            for key in flag_keys:
                flag_data = await self.get_flag(key)
                if flag_data:
                    flags[key] = flag_data
            
            return flags
        except Exception as e:
            logger.error(f"Failed to get all flags details: {e}")
            return {}


_flag_manager: Optional[FeatureFlagManager] = None


def get_flag_manager() -> FeatureFlagManager:
    """Get the global feature flag manager instance"""
    global _flag_manager
    if _flag_manager is None:
        _flag_manager = FeatureFlagManager()
    return _flag_manager


# Async convenience functions
async def set_flag(key: str, enabled: bool, description: str = "") -> bool:
    return await get_flag_manager().set_flag(key, enabled, description)


async def is_enabled(key: str) -> bool:
    return await get_flag_manager().is_enabled(key)


async def enable_flag(key: str, description: str = "") -> bool:
    return await set_flag(key, True, description)


async def disable_flag(key: str, description: str = "") -> bool:
    return await set_flag(key, False, description)


async def delete_flag(key: str) -> bool:
    return await get_flag_manager().delete_flag(key)


async def list_flags() -> Dict[str, bool]:
    return await get_flag_manager().list_flags()


async def get_flag_details(key: str) -> Optional[Dict[str, str]]:
    return await get_flag_manager().get_flag(key)


# Feature Flags

# Fufanmanus default agent feature flag
fufanmanus_default_agent = True

# Custom agents feature flag
custom_agents = True

# MCP module feature flag  
mcp_module = False

# Templates API feature flag
templates_api = False

# Triggers API feature flag
triggers_api = False

# Workflows API feature flag
workflows_api = False

# Knowledge base feature flag
knowledge_base = False

# Pipedream integration feature flag
pipedream = False

# Credentials API feature flag
credentials_api = False





