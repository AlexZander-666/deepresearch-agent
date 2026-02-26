'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from 'react';
import { authClient, User, Session } from '@/lib/auth/client';

type AuthContextType = {
  supabase: any;
  session: Session | null;
  user: User | null;
  isLoading: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // 获取初始session
    const getInitialSession = async () => {
      try {
        const { data: { session: currentSession }, error } = await authClient.instance.getSession();
        if (currentSession && !error) {
          setSession(currentSession);
          setUser(currentSession.user);
        }
      } catch (error) {
        console.error('Failed to get initial session:', error);
      } finally {
        setIsLoading(false);
      }
    };

    getInitialSession();

    // 监听认证状态变化
    const { data: { subscription } } = authClient.instance.onAuthStateChange((event, newSession) => {
      setSession(newSession);
      setUser(newSession?.user ?? null);
      
      if (isLoading) setIsLoading(false);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, [isLoading]);

  const signOut = async () => {
    try {
      await authClient.instance.signOut();
      setSession(null);
      setUser(null);
    } catch (error) {
      console.error('❌ Error signing out:', error);
    }
  };

  const value = {
    supabase: authClient.instance, // 提供认证客户端而不是数据库客户端
    session,
    user,
    isLoading,
    signOut,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
