const TOKEN_KEY = "klicklab_token";
const EXPIRES_KEY = "klicklab_expiresAt";
const AUTO_LOGIN_KEY = "klicklab_autoLogin";
// 예전 버전이 이메일/비밀번호를 평문으로 저장하던 키 (더 이상 사용하지 않으며, 남아 있으면 삭제한다)
const LEGACY_CREDENTIALS_KEY = "klicklab_credentials";

export const purgeLegacyCredentials = () => {
  try {
    localStorage.removeItem(LEGACY_CREDENTIALS_KEY);
  } catch {
    // 저장소 접근이 막힌 환경에서는 무시
  }
};
purgeLegacyCredentials();

// 자동 로그인 여부에 따라 저장소 결정
const getStorage = (isAutoLogin: boolean): Storage =>
  isAutoLogin ? localStorage : sessionStorage;

// 저장소에 accessToken과 만료 시각 저장
export const setToken = (
  token: string,
  expiresInMs: number,
  isAutoLogin: boolean
) => {
  const storage = getStorage(isAutoLogin);
  const expiresAt = Date.now() + expiresInMs;

  storage.setItem(TOKEN_KEY, token);
  storage.setItem(EXPIRES_KEY, String(expiresAt));
};

// 저장된 accessToken을 가져옴 (로컬 → 세션 순서)
export const getToken = (): string | null =>
  localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);

// 저장된 만료 시각을 가져옴 (로컬 → 세션 순서)
export const getExpiresAt = (): number =>
  Number(localStorage.getItem(EXPIRES_KEY)) ||
  Number(sessionStorage.getItem(EXPIRES_KEY)) ||
  0;

// 저장된 토큰과 만료 시각 삭제 (양쪽 다 삭제)
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRES_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(EXPIRES_KEY);
};

// 현재 저장소가 local인지 session인지 확인
export const isUsingLocalStorage = (): boolean =>
  !!localStorage.getItem(TOKEN_KEY);

// 자동 로그인 여부만 저장한다. 자격 증명(이메일/비밀번호)은 어디에도 저장하지 않으며,
// 로그인 유지는 서버가 내려준 HttpOnly refreshToken 쿠키로 처리한다.
export const setAutoLogin = (enabled: boolean) => {
  localStorage.setItem(AUTO_LOGIN_KEY, String(enabled));
};

// 자동 로그인 설정 가져오기
export const getAutoLogin = (): boolean => {
  return localStorage.getItem(AUTO_LOGIN_KEY) === 'true';
};
