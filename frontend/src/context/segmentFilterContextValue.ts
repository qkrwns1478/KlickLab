import { createContext, useContext } from 'react';

export interface SegmentFilter {
  id: string;
  name: string;
  segment: string;
  conditions: Record<string, any>;
  createdAt: number;
  [key: string]: any;
}

export interface SegmentFilterContextType {
  filter: SegmentFilter;
  setFilter: (filter: SegmentFilter | ((prev: SegmentFilter) => SegmentFilter)) => void;
  savedFilters: SegmentFilter[];
  saveFilter: (filter: SegmentFilter) => void;
  loadFilter: (filterId: string) => void;
  deleteFilter: (filterId: string) => void;
  generateFilterName: (conditions: Record<string, any>) => string;
}

export const SegmentFilterContext = createContext<SegmentFilterContextType | undefined>(undefined);

export const useSegmentFilter = () => {
  const ctx = useContext(SegmentFilterContext);
  if (!ctx) throw new Error('useSegmentFilter must be used within SegmentFilterProvider');
  return ctx;
};
