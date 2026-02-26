# 环境变量配置说明

## 必需的环境变量

请在 `.env` 文件中配置以下环境变量：

```env
# PPIO 沙箱基础配置
E2B_DOMAIN=sandbox.ppio.cn
E2B_API_KEY=sk_***  # 你的 PPIO API 密钥

# PPIO 沙箱模板 ID 配置（使用你控制台中的模板ID）
SANDBOX_TEMPLATE_CODE=br263f8awvhrqd7ss1ze           # code-interpreter-v1
SANDBOX_TEMPLATE_DESKTOP=4imxoe43snzcxj95hvha        # desktop (VNC)
SANDBOX_TEMPLATE_BROWSER=7xvs3snis3tkuq3y8u96        # browser-chromium  
SANDBOX_TEMPLATE_BASE=txi15v1zt0q72i1gcyqb           # base

# 其他API配置
TAVILY_API_KEY=your_tavily_api_key
FIRECRAWL_API_KEY=your_firecrawl_api_key
FIRECRAWL_URL=https://api.firecrawl.dev

# 数据库配置
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
```

## 获取模板ID

1. 登录 [PPIO 控制台](https://ppio.com/console)
2. 查看你的沙箱模板列表
3. 复制对应模板的ID到环境变量中

## 调试提示

如果出现 `can only concatenate str (not "list") to str` 错误：

1. 检查环境变量是否正确配置
2. 查看日志中的详细错误信息
3. 确认 PPIO API 密钥有效
4. 确认模板ID存在且有权限访问 