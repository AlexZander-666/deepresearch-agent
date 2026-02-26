// 新的认证客户端 - 替代Supabase认证
import { BACKEND_URL } from '@/lib/env';

const API_URL = BACKEND_URL || 'http://localhost:8000/api';

// 调试信息
console.log('🔧 Auth Client API_URL:', API_URL);

export interface User {
  id: string;
  email: string;
  name?: string;
  created_at?: string;
}

export interface Session {
  access_token: string;
  refresh_token: string;
  user: User;
  expires_at?: number;
}

export interface AuthResponse {
  session: Session | null;
  user: User | null;
  error: string | null;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterCredentials {
  email: string;
  password: string;
  name?: string;
}

class AuthClient {
  private session: Session | null = null;
  private refreshTimeout: NodeJS.Timeout | null = null;

  constructor() {
    // 从localStorage恢复session
    this.loadSessionFromStorage();
    this.setupTokenRefresh();
  }

  // 登录
  async signIn(credentials: LoginCredentials): Promise<AuthResponse> {
    try {
      console.log('🚀 发送登录请求到:', `${API_URL}/auth/login`);
      console.log('📝 登录数据:', credentials);
      
      const response = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(credentials),
      });

      const data = await response.json();

      if (!response.ok) {
        return {
          session: null,
          user: null,
          error: data.message || 'Login failed'
        };
      }

      const session: Session = {
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        user: data.user,
        expires_at: data.expires_at
      };

      this.setSession(session);
      
      return {
        session,
        user: data.user,
        error: null
      };

    } catch (error: any) {
      return {
        session: null,
        user: null,
        error: error.message || 'Network error'
      };
    }
  }

  // 注册
  async signUp(credentials: RegisterCredentials): Promise<AuthResponse> {
    try {
      console.log('🚀 发送注册请求到:', `${API_URL}/auth/register`);
      console.log('📝 注册数据:', credentials);
      
      const response = await fetch(`${API_URL}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(credentials),
      });

      console.log('📡 响应状态:', response.status);
      console.log('📡 响应头:', Object.fromEntries(response.headers.entries()));
      
      const data = await response.json();
      console.log('📡 响应数据:', data);

      if (!response.ok) {
        return {
          session: null,
          user: null,
          error: data.message || 'Registration failed'
        };
      }

      // 注册成功后自动登录
      return this.signIn({
        email: credentials.email,
        password: credentials.password
      });

    } catch (error: any) {
      console.error('❌ 注册请求失败:', error);
      console.error('❌ 错误详情:', {
        message: error.message,
        stack: error.stack,
        name: error.name
      });
      return {
        session: null,
        user: null,
        error: error.message || 'Network error'
      };
    }
  }

  // 登出
  async signOut(): Promise<{ error: string | null }> {
    try {
      if (this.session?.refresh_token) {
        await fetch(`${API_URL}/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.session.access_token}`,
          },
          body: JSON.stringify({
            refresh_token: this.session.refresh_token
          }),
        });
      }
    } catch (error) {
      console.warn('Logout request failed:', error);
    }

    this.clearSession();
    return { error: null };
  }

  // 获取当前session
  async getSession(): Promise<{ data: { session: Session | null }, error: string | null }> {
    if (!this.session) {
      return {
        data: { session: null },
        error: null
      };
    }

    // 检查token是否即将过期，如果是则刷新
    if (this.isTokenExpiringSoon()) {
      const refreshResult = await this.refreshToken();
      if (refreshResult.error) {
        this.clearSession();
        return {
          data: { session: null },
          error: refreshResult.error
        };
      }
    }

    return {
      data: { session: this.session },
      error: null
    };
  }

  // 获取当前用户
  async getUser(): Promise<{ data: { user: User | null }, error: string | null }> {
    try {
      const { data: { session }, error } = await this.getSession();
      
      if (error || !session) {
        return {
          data: { user: null },
          error
        };
      }

      // 调用后端API获取最新的用户信息
      const response = await fetch(`${API_URL}/auth/me`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.access_token}`,
        },
      });

      if (!response.ok) {
        return {
          data: { user: session.user }, // 如果API失败，返回session中的用户信息
          error: null
        };
      }

      const userData = await response.json();
      return {
        data: { user: userData },
        error: null
      };
    } catch (error: any) {
      // 如果API调用失败，返回session中的用户信息
      const { data: { session }, error: sessionError } = await this.getSession();
      return {
        data: { user: session?.user || null },
        error: sessionError
      };
    }
  }

  // 刷新token
  async refreshToken(): Promise<{ session: Session | null, error: string | null }> {
    if (!this.session?.refresh_token) {
      return { session: null, error: 'No refresh token available' };
    }

    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          refresh_token: this.session.refresh_token
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        this.clearSession();
        return { session: null, error: data.message || 'Token refresh failed' };
      }

      const newSession: Session = {
        access_token: data.access_token,
        refresh_token: data.refresh_token || this.session.refresh_token,
        user: data.user || this.session.user,
        expires_at: data.expires_at
      };

      this.setSession(newSession);
      return { session: newSession, error: null };

    } catch (error: any) {
      this.clearSession();
      return { session: null, error: error.message || 'Network error' };
    }
  }

  // 监听认证状态变化
  onAuthStateChange(callback: (event: string, session: Session | null) => void) {
    // 简单实现，可以扩展为完整的事件系统
    const checkAuthState = () => {
      if (this.session) {
        callback('SIGNED_IN', this.session);
      } else {
        callback('SIGNED_OUT', null);
      }
    };

    // 立即执行一次
    checkAuthState();

    // 返回取消订阅函数
    return {
      data: {
        subscription: {
          unsubscribe: () => {
            // 清理逻辑
          }
        }
      }
    };
  }

  // 私有方法：设置session
  private setSession(session: Session) {
    this.session = session;
    if (typeof window !== 'undefined') {
      localStorage.setItem('auth_session', JSON.stringify(session));
    }
    this.setupTokenRefresh();
  }

  // 私有方法：清除session
  private clearSession() {
    this.session = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('auth_session');
    }
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
      this.refreshTimeout = null;
    }
  }

  // 私有方法：从本地存储加载session
  private loadSessionFromStorage() {
    // 只在客户端运行
    if (typeof window === 'undefined') {
      return;
    }
    
    try {
      const storedSession = localStorage.getItem('auth_session');
      if (storedSession) {
        this.session = JSON.parse(storedSession);
      }
    } catch (error) {
      console.warn('Failed to load session from storage:', error);
      if (typeof window !== 'undefined') {
        localStorage.removeItem('auth_session');
      }
    }
  }

  // 私有方法：检查token是否即将过期
  private isTokenExpiringSoon(): boolean {
    if (!this.session?.expires_at) {
      return false;
    }

    const now = Date.now() / 1000;
    const expiresAt = this.session.expires_at;
    
    // 如果token在5分钟内过期，就认为需要刷新
    return (expiresAt - now) < 300;
  }

  // 私有方法：设置自动token刷新
  private setupTokenRefresh() {
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
    }

    if (!this.session?.expires_at) {
      return;
    }

    const now = Date.now() / 1000;
    const expiresAt = this.session.expires_at;
    
    // 在token过期前5分钟自动刷新
    const refreshIn = Math.max(0, (expiresAt - now - 300) * 1000);

    this.refreshTimeout = setTimeout(async () => {
      await this.refreshToken();
    }, refreshIn);
  }
}

// 创建全局实例 - 只在客户端创建
let authClientInstance: AuthClient | null = null;

export const authClient = {
  get instance() {
    if (typeof window === 'undefined') {
      // 服务端返回空对象
      return {
        signIn: async () => ({ error: 'Client-side only', session: null }),
        signUp: async () => ({ error: 'Client-side only', session: null }),
        signOut: async () => {},
        getSession: async () => ({ data: { session: null }, error: null }),
        getUser: async () => ({ data: { user: null }, error: null }),
        refreshToken: async () => ({ error: 'Client-side only' }),
        onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } })
      };
    }
    
    if (!authClientInstance) {
      authClientInstance = new AuthClient();
    }
    return authClientInstance;
  }
};

// 兼容原有的createClient接口
export function createClient() {
  return {
    auth: authClient.instance,
    // 添加数据库相关方法以兼容现有代码
    from: (table: string) => ({
      select: () => ({ eq: () => ({ data: null, error: null }) }),
      insert: () => ({ data: null, error: null }),
      update: () => ({ eq: () => ({ data: null, error: null }) }),
      delete: () => ({ eq: () => ({ data: null, error: null }) }),
    }),
    // 添加存储相关方法
    storage: {
      from: () => ({
        upload: () => ({ data: null, error: null }),
        download: () => ({ data: null, error: null }),
        remove: () => ({ data: null, error: null }),
      })
    }
  };
} 
