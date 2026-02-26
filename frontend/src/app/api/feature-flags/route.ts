import { getServerBackendUrl } from '@/lib/env';
import { NextResponse } from 'next/server';

const FALLBACK = { flags: {} as Record<string, boolean> };

export async function GET() {
  try {
    const backendUrl = getServerBackendUrl();
    const response = await fetch(`${backendUrl}/feature-flags`, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
      },
    });

    if (!response.ok) {
      return NextResponse.json(FALLBACK);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(FALLBACK);
  }
}
