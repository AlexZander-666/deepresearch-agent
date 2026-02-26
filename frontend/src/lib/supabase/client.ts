import { createClient as createAuthClient } from '../auth/client';
import { createClient as createDatabaseClient } from '../database/client';

type RpcResult<T = unknown> = Promise<{ data: T | null; error: unknown }>;

type SupabaseLikeClient = {
  auth: ReturnType<typeof createAuthClient>['auth'];
  from: ReturnType<typeof createDatabaseClient>['from'];
  rpc: <T = unknown>(
    functionName: string,
    params?: Record<string, unknown>,
  ) => RpcResult<T>;
  storage: ReturnType<typeof createDatabaseClient>['storage'];
};

// Combine auth session support with database/rpc compatibility.
export function createClient(): SupabaseLikeClient {
  const authClient = createAuthClient();
  const databaseClient = createDatabaseClient();

  return {
    auth: authClient.auth,
    from: databaseClient.from.bind(databaseClient),
    rpc: databaseClient.rpc.bind(databaseClient),
    storage: databaseClient.storage,
  };
}
