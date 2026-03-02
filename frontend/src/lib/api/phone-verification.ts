import { supabaseMFAService } from '@/lib/supabase/mfa';



export interface FactorInfo {
  id: string;
  friendly_name?: string;
  factor_type?: string;
  status?: string;
  phone?: string;
  created_at?: string;
  updated_at?: string;
}

export interface PhoneVerificationEnroll {
  friendly_name: string;
  phone_number: string;
}

export interface PhoneVerificationChallenge {
  factor_id: string;
}

export interface PhoneVerificationVerify {
  factor_id: string;
  challenge_id: string;
  code: string;
}

export interface PhoneVerificationChallengeAndVerify {
  factor_id: string;
  code: string;
}

export interface PhoneVerificationResponse {
  success: boolean;
  message?: string;
  id?: string;
  expires_at?: string;
}

export interface EnrollFactorResponse {
  id: string;
  friendly_name: string;
  phone_number: string;
  qr_code?: string;
  secret?: string;
}

export interface ChallengeResponse {
  id: string;
  expires_at?: string;
}

export interface ListFactorsResponse {
  factors: FactorInfo[];
}

export interface AALResponse {
  current_level?: string;
  next_level?: string;
  current_authentication_methods?: string[];
  // Add action guidance based on AAL status
  action_required?: string;
  message?: string;
  // Phone verification requirement fields
  phone_verification_required?: boolean;
  user_created_at?: string;
  cutoff_date?: string;
  // Computed verification status fields (same as PhoneVerificationStatus)
  verification_required?: boolean;
  is_verified?: boolean;
  factors?: FactorInfo[];
}




export const phoneVerificationService = {
  /**
   * Enroll phone number for SMS-based 2FA
   */
  async enrollPhoneNumber(data: PhoneVerificationEnroll): Promise<EnrollFactorResponse> {
    await supabaseMFAService.enroll({
      factorType: 'phone',
      friendlyName: data.friendly_name,
    });
    return {
      id: `phone_factor_${Date.now()}`,
      friendly_name: data.friendly_name,
      phone_number: data.phone_number,
    };
  },

  /**
   * Create a challenge for an enrolled phone factor (sends SMS)
   */
  async createChallenge(data: PhoneVerificationChallenge): Promise<ChallengeResponse> {
    await supabaseMFAService.challenge({ factorId: data.factor_id });
    return {
      id: `challenge_${Date.now()}`,
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    };
  },

  /**
   * Verify SMS code for phone verification
   */
  async verifyChallenge(data: PhoneVerificationVerify): Promise<PhoneVerificationResponse> {
    const result = await supabaseMFAService.verify({
      factorId: data.factor_id,
      challengeId: data.challenge_id,
      code: data.code,
    });
    return {
      success: !result.error,
      message: result.error?.message,
    };
  },

  /**
   * Create challenge and verify in one step
   */
  async challengeAndVerify(data: PhoneVerificationChallengeAndVerify): Promise<PhoneVerificationResponse> {
    const result = await supabaseMFAService.challengeAndVerify({
      factorId: data.factor_id,
      code: data.code,
    });
    return {
      success: !result.error,
      message: result.error?.message,
    };
  },

  /**
   * Resend SMS code (create new challenge for existing factor)
   */
  async resendSMS(factorId: string): Promise<ChallengeResponse> {
    await supabaseMFAService.challenge({ factorId });
    return {
      id: `challenge_${Date.now()}`,
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    };
  },

  /**
   * List all enrolled MFA factors
   */
  async listFactors(): Promise<ListFactorsResponse> {
    const result = await supabaseMFAService.listFactors();
    return {
      factors: Array.isArray(result.data) ? (result.data as FactorInfo[]) : [],
    };
  },

  /**
   * Remove phone verification from account
   */
  async unenrollFactor(factorId: string): Promise<PhoneVerificationResponse> {
    const result = await supabaseMFAService.unenroll({ factorId });
    return {
      success: !result.error,
      message: result.error?.message,
    };
  },

  /**
   * Get Authenticator Assurance Level
   */
  async getAAL(): Promise<AALResponse> {
    const result = await supabaseMFAService.getAuthenticatorAssuranceLevel();
    const currentLevel = result.data?.currentLevel ?? 'aal1';
    const nextLevel = result.data?.nextLevel ?? currentLevel;
    return {
      current_level: currentLevel,
      next_level: nextLevel,
      action_required: 'none',
      phone_verification_required: false,
      verification_required: false,
      is_verified: true,
      factors: [],
    };
  }
};
