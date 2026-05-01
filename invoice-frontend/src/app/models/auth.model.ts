export interface AuthUser {
  user_id: string;
  username: string;
  role: 'admin' | 'comptable' | string;
  display_name: string;
  permissions?: string[];
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  display_name?: string;
}

export interface RefreshRequest {
  refresh_token: string;
}
