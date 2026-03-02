export type LegalTab = 'terms' | 'privacy';

export function getLegalTabFromParam(tabParam: string | null): LegalTab {
  return tabParam === 'privacy' ? 'privacy' : 'terms';
}

export function getNextLegalTabUrl(
  pathname: string,
  searchParams: URLSearchParams | { toString(): string; get(name: string): string | null },
  nextTab: LegalTab,
): string | null {
  const currentTab = searchParams.get('tab');
  if (currentTab === nextTab) {
    return null;
  }

  const params = new URLSearchParams(searchParams.toString());
  params.set('tab', nextTab);

  return `${pathname}?${params.toString()}`;
}
