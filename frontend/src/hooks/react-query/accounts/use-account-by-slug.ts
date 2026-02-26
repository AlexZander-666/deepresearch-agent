import { useQuery } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { GetAccountResponse } from '@usebasejump/shared';

export function useAccountBySlug(slug: string) {
  const supabaseClient = createClient();
  
  return useQuery<GetAccountResponse | null, Error>({
    queryKey: ['account', 'by-slug', slug],
    queryFn: async () => {
      const { data, error } = await supabaseClient.rpc<GetAccountResponse>(
        'get_account_by_slug',
        {
          slug,
        },
      );

      if (error) {
        throw new Error(
          error instanceof Error
            ? error.message
            : 'Failed to fetch account by slug',
        );
      }

      return data ?? null;
    },
    enabled: !!slug && !!supabaseClient,
  });
}
