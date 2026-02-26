import { getServerBackendUrl } from '@/lib/env';
import { NextResponse } from 'next/server';

type Params = { params: Promise<{ flagName: string }> };

export async function GET(_: Request, { params }: Params) {
  const { flagName } = await params;
  const fallback = {
    flag_name: flagName,
    enabled: false,
    details: null,
  };

  try {
    const backendUrl = getServerBackendUrl();
    const response = await fetch(`${backendUrl}/feature-flags/${flagName}`, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
      },
    });

    if (!response.ok) {
      return NextResponse.json(fallback);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(fallback);
  }
}
