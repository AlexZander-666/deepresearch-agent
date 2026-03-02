'use client';

import { useState } from 'react';
import {
  type DehydratedState,
  HydrationBoundary,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';

import { handleApiError } from '@/lib/error-handler';
export function ReactQueryProvider({
  children,
  dehydratedState,
}: {
  children: React.ReactNode;
  dehydratedState?: unknown;
}) {
  const hydrationState: DehydratedState | undefined =
    dehydratedState &&
    typeof dehydratedState === 'object' &&
    'queries' in dehydratedState &&
    'mutations' in dehydratedState
      ? (dehydratedState as DehydratedState)
      : undefined;

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 20 * 1000,
            gcTime: 5 * 60 * 1000,
            retry: (failureCount, error: any) => {
              if (error?.status >= 400 && error?.status < 500) return false;
              if (error?.status === 404) return false;
              return failureCount < 3;
            },
            refetchOnMount: true,
            refetchOnWindowFocus: true,
            refetchOnReconnect: 'always',
          },
          mutations: {
            retry: (failureCount, error: any) => {
              if (error?.status >= 400 && error?.status < 500) return false;
              return failureCount < 1;
            },
            onError: (error: any, variables: any, context: any) => {
              handleApiError(error, {
                operation: 'perform action',
                silent: false,
              });
            },
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <HydrationBoundary state={hydrationState}>
        {children}

      </HydrationBoundary>
    </QueryClientProvider>
  );
}
