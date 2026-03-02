'use client';

import { useEffect } from 'react';
import { debugLog } from '@/lib/client-logger';

export const PostHogIdentify = () => {
  useEffect(() => {
    debugLog('PostHog tracking without authentication');
  }, []);

  return null;
};
