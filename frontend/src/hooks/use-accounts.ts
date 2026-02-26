import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { GetAccountsResponse } from '@usebasejump/shared';

type AccountsQueryOptions = Omit<
  UseQueryOptions<GetAccountsResponse, Error, GetAccountsResponse, ['accounts']>,
  'queryKey' | 'queryFn'
>;

export const useAccounts = (options?: AccountsQueryOptions) => {
  const supabaseClient = createClient();
  return useQuery<GetAccountsResponse, Error, GetAccountsResponse, ['accounts']>({
    queryKey: ['accounts'],
    queryFn: async () => {
      const { data, error } = await supabaseClient.rpc<GetAccountsResponse>(
        'get_accounts',
      );
      if (error) {
        throw new Error(
          error instanceof Error ? error.message : 'Failed to fetch accounts',
        );
      }
      return data ?? [];
    },
    ...options,
  });
};
