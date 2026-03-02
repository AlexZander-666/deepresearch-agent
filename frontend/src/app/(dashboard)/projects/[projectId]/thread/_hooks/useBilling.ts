import { useCallback, useState } from 'react';
import { BillingData, AgentStatus } from '../_types';

interface UseBillingReturn {
  showBillingAlert: boolean;
  setShowBillingAlert: React.Dispatch<React.SetStateAction<boolean>>;
  billingData: BillingData;
  setBillingData: React.Dispatch<React.SetStateAction<BillingData>>;
  checkBillingLimits: () => Promise<boolean>;
}

export function useBilling(
  projectAccountId: string | null | undefined,
  agentStatus: AgentStatus,
  initialLoadCompleted: boolean
): UseBillingReturn {
  const [showBillingAlert, setShowBillingAlert] = useState(false);
  const [billingData, setBillingData] = useState<BillingData>({});

  const checkBillingLimits = useCallback(async () => {
    return false;
  }, []);

  return {
    showBillingAlert,
    setShowBillingAlert,
    billingData,
    setBillingData,
    checkBillingLimits,
  };
} 
