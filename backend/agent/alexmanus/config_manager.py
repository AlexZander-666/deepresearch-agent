import datetime
from typing import Dict, Any
from dataclasses import dataclass
from agent.alexmanus.config import AlexManusConfig


@dataclass
class AlexManusConfiguration:
    name: str
    description: str
    configured_mcps: list
    custom_mcps: list
    restrictions: Dict[str, Any]
    version_tag: str


class AlexManusConfigManager:
    def get_current_config(self) -> AlexManusConfiguration:
        version_tag = self._generate_version_tag()
        
        return AlexManusConfiguration(
            name=AlexManusConfig.NAME,
            description=AlexManusConfig.DESCRIPTION,
            configured_mcps=AlexManusConfig.DEFAULT_MCPS.copy(),
            custom_mcps=AlexManusConfig.DEFAULT_CUSTOM_MCPS.copy(),
            restrictions=AlexManusConfig.USER_RESTRICTIONS.copy(),
            version_tag=version_tag
        )
    
    def has_config_changed(self, last_version_tag: str) -> bool:
        current = self.get_current_config()
        return current.version_tag != last_version_tag
    
    def validate_config(self, config: AlexManusConfiguration) -> tuple[bool, list[str]]:
        errors = []
        
        if not config.name.strip():
            errors.append("Name cannot be empty")
            
        return len(errors) == 0, errors
    
    def _generate_version_tag(self) -> str:
        import hashlib
        import json
        
        config_data = {
            "name": AlexManusConfig.NAME,
            "description": AlexManusConfig.DESCRIPTION,
            "system_prompt": AlexManusConfig.get_system_prompt(),
            "default_tools": AlexManusConfig.DEFAULT_TOOLS,
            "avatar": AlexManusConfig.AVATAR,
            "avatar_color": AlexManusConfig.AVATAR_COLOR,
            "restrictions": AlexManusConfig.USER_RESTRICTIONS,
        }
        
        config_str = json.dumps(config_data, sort_keys=True)
        hash_obj = hashlib.md5(config_str.encode())
        return f"config-{hash_obj.hexdigest()[:8]}" 