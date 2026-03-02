export type DashboardLoadingState = {
  authLoading: boolean;
  healthLoading: boolean;
  healthStatus?: string;
  healthError: unknown;
};

export const shouldShowDashboardLoading = ({
  authLoading,
  healthLoading,
  healthStatus,
  healthError,
}: DashboardLoadingState): boolean => {
  if (authLoading) {
    return true;
  }

  // Only block rendering during the very first health check.
  // Once we already have an error or health result, avoid bouncing back to
  // a full-page spinner while background retries happen.
  return healthLoading && !healthError && healthStatus !== 'ok';
};
