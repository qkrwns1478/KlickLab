import { createContext, useContext } from 'react';

export interface ConversionEventContextValue {
  currentEvent: string | null;
  updateEvent: (event: string) => void;
}

export const ConversionEventContext = createContext<ConversionEventContextValue | null>(null);

// Context를 쉽게 쓰기 위한 커스텀 훅
export const useConversionEvent = () => {
  const context = useContext(ConversionEventContext);
  if (!context) throw new Error('useConversionEvent must be used within ConversionEventProvider');
  return context;
};
