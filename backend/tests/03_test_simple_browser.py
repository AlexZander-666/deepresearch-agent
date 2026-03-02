import asyncio
import base64
import os
import time
from dotenv import load_dotenv
from typing import Optional, Tuple

# 仅补全缺失变量，避免覆盖运行时注入的密钥
load_dotenv(override=False)

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatOpenAI
from e2b_code_interpreter import Sandbox

def resolve_llm_settings() -> Tuple[str, str, Optional[str]]:
    """
    解析 browser-use 所需的 LLM 配置。
    优先使用 DeepSeek/Qwen 兼容配置，回退 OpenAI。
    """
    model_name = (
        os.getenv("BROWSER_USE_MODEL")
        or os.getenv("QWEN_TEXT_MODEL")
        or os.getenv("MODEL_TO_USE")
        or "gpt-4o"
    )

    model_name_lower = model_name.lower()
    if "deepseek" in model_name_lower or "qwen" in model_name_lower:
        api_key = os.getenv("QWEN_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("QWEN_API_BASE") or os.getenv("DEEPSEEK_API_BASE") or os.getenv("OPENAI_BASE_URL")
    else:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("QWEN_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("未找到可用的 LLM API Key，请检查 OPENAI_API_KEY / DEEPSEEK_API_KEY / QWEN_API_KEY")

    return model_name, api_key, base_url

def save_screenshots_from_history(history, session_id: str):
    """根据官方文档保存截图的方法"""
    print(f"\n🖼️  正在保存截图 (会话ID: {session_id})...")
    
    try:
        # 创建截图目录
        screenshots_dir = os.path.join(".", "screenshots", str(session_id))
        os.makedirs(screenshots_dir, exist_ok=True)
        
        saved_screenshots = []
        
        # 方法A: 使用 history.screenshots() 获取base64截图
        screenshots_b64 = [img for img in history.screenshots() if isinstance(img, str) and img]
        print(f"📸 找到 {len(screenshots_b64)} 个base64截图")
        
        for i, b64img in enumerate(screenshots_b64):
            try:
                # 解码base64
                encoded = b64img.split(",", 1)[1] if "," in b64img else b64img
                img_data = base64.b64decode(encoded)
                
                # 生成文件名
                screenshot_path = os.path.join(screenshots_dir, f"screenshot_{i:02d}_{time.time():.0f}.png")
                
                # 保存文件
                with open(screenshot_path, "wb") as f:
                    f.write(img_data)
                
                saved_screenshots.append(screenshot_path)
                print(f"✅ 截图 {i+1} 已保存: {screenshot_path}")
                
            except Exception as e:
                print(f"❌ 保存截图 {i+1} 失败: {e}")
        
        # 方法B: 使用 history.screenshot_paths() 获取临时文件路径
        temp_paths = [path for path in history.screenshot_paths() if isinstance(path, str) and path]
        print(f"📁 找到 {len(temp_paths)} 个临时截图文件")
        
        for i, temp_path in enumerate(temp_paths):
            try:
                if os.path.exists(temp_path):
                    # 复制到我们的目录
                    final_path = os.path.join(screenshots_dir, f"temp_screenshot_{i:02d}_{time.time():.0f}.png")
                    
                    # 读取临时文件并复制
                    with open(temp_path, "rb") as src:
                        with open(final_path, "wb") as dst:
                            dst.write(src.read())
                    
                    saved_screenshots.append(final_path)
                    print(f"✅ 临时截图 {i+1} 已复制: {final_path}")
                else:
                    print(f"⚠️  临时文件不存在: {temp_path}")
                    
            except Exception as e:
                print(f"❌ 复制临时截图 {i+1} 失败: {e}")
        
        print(f"🎉 截图保存完成! 共保存 {len(saved_screenshots)} 个文件")
        return saved_screenshots
        
    except Exception as e:
        print(f"❌ 截图保存过程出错: {e}")
        import traceback
        traceback.print_exc()
        return []

async def main():
    print("🚀 启动 browser-use 官方截图方案...")
    print(f"E2B API Key: {os.getenv('E2B_API_KEY')[:20]}...")
    print(f"E2B Domain: {os.getenv('E2B_DOMAIN')}")
    model_name, llm_api_key, llm_base_url = resolve_llm_settings()
    print(f"LLM Model: {model_name}")
    print(f"LLM Key: {llm_api_key[:8]}...{llm_api_key[-4:]}")
    if llm_base_url:
        print(f"LLM Base URL: {llm_base_url}")
    
    sandbox = Sandbox(
        timeout=600,
        template="browser-chromium",
    )
    
    try:
        # 获取Chrome调试地址
        host = sandbox.get_host(9223)
        cdp_url = f"https://{host}"
        print(f"Chrome CDP URL: {cdp_url}")
        
        # 创建浏览器会话
        browser_session = BrowserSession(cdp_url=cdp_url)
        await browser_session.start()
        print("✅ BrowserSession 启动成功")

        llm_kwargs = {
            "api_key": llm_api_key,
            "model": model_name,
            "temperature": 0,
        }
        if llm_base_url:
            llm_kwargs["base_url"] = llm_base_url

        task_prompt = (
            "请完成以下任务："
            "1) 打开百度并搜索 Browser-use；"
            "2) 在首页和搜索结果页都停留；"
            "3) 输出 3 个 Browser-use 使用场景总结。"
            "只使用 go_to_url、input_text、click_element_by_index、wait、done 这些动作。"
            "不要使用 extract_structured_data。"
        )

        print("🤖 开始执行Agent任务...")
        agent = Agent(
            task=task_prompt,
            llm=ChatOpenAI(**llm_kwargs),
            browser_session=browser_session,
            use_vision=False,               # DeepSeek/Qwen 兼容性更稳定
            include_tool_call_examples=True,
            use_thinking=False,
            max_actions_per_step=1,
            max_failures=6,
        )
        history = await agent.run(max_steps=12)
        
        print(f"✅ Agent任务完成!")
        print(f"📊 执行步骤: {history.number_of_steps()}")
        print(f"⏱️  总用时: {history.total_duration_seconds():.2f} 秒")
        print(f"🌐 访问的URLs: {history.urls()}")
        
        # 检查是否成功（部分模型会返回 final_result 但 success 标记为 False）
        final_result = history.final_result()
        task_success = history.is_successful() or bool(final_result and str(final_result).strip())
        if task_success:
            print("🎯 任务执行成功!")
        else:
            print("⚠️  任务可能未完全成功")
        
        # 保存截图（核心功能！）
        screenshots = save_screenshots_from_history(history, browser_session.id)
        
        # 显示最终结果
        if final_result:
            print(f"\n📋 最终结果: {final_result}")
        
        # 关闭浏览器会话
        await browser_session.stop()
        print("✅ BrowserSession 已停止")
        
        return screenshots
        
    except Exception as e:
        print(f"❌ 主程序出错: {e}")
        import traceback
        traceback.print_exc()
        return []
        
    finally:
        # 清理沙箱
        sandbox.kill()
        print("🧹 沙箱已清理")

if __name__ == "__main__":
    screenshots = asyncio.run(main())
    print(f"\n🏁 程序完成! 保存了 {len(screenshots)} 个截图文件")
    for path in screenshots:
        print(f"   📸 {path}") 
