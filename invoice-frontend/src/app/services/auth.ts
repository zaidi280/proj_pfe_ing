import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, catchError, map, of, tap, throwError } from 'rxjs';
import { API_URL } from '../app.config';
import { AuthTokens, AuthUser, LoginRequest, RegisterRequest } from '../models/auth.model';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly accessTokenKey = 'invoice_auth_access_token';
  private readonly refreshTokenKey = 'invoice_auth_refresh_token';
  private readonly userKey = 'invoice_auth_user';

  private currentUserSubject = new BehaviorSubject<AuthUser | null>(this.readUser());
  readonly currentUser$ = this.currentUserSubject.asObservable();

  constructor(private http: HttpClient) {}

  login(payload: LoginRequest): Observable<AuthTokens> {
    return this.http.post<AuthTokens>(`${API_URL}/auth/login`, payload).pipe(
      tap((response) => this.applySession(response))
    );
  }

  register(payload: RegisterRequest): Observable<AuthTokens> {
    return this.http.post<AuthTokens>(`${API_URL}/auth/register`, payload).pipe(
      tap((response) => this.applySession(response))
    );
  }

  listComptables(limit = 500): Observable<any> {
    return this.http.get<any>(`${API_URL}/auth/comptables?limit=${encodeURIComponent(String(limit))}`);
  }

  createComptable(payload: { username: string; password: string; display_name?: string; permissions?: string[] }): Observable<any> {
    return this.http.post<any>(`${API_URL}/auth/comptables`, payload);
  }

  updateComptable(
    userId: string,
    payload: { display_name?: string; password?: string; is_active?: boolean; permissions?: string[] }
  ): Observable<any> {
    return this.http.patch<any>(`${API_URL}/auth/comptables/${encodeURIComponent(userId)}`, payload);
  }

  deactivateComptable(userId: string): Observable<any> {
    return this.http.delete<any>(`${API_URL}/auth/comptables/${encodeURIComponent(userId)}`);
  }

  refreshSession(): Observable<string> {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      return throwError(() => new Error('No refresh token available'));
    }

    return this.http.post<AuthTokens>(`${API_URL}/auth/refresh`, { refresh_token: refreshToken }).pipe(
      tap((response) => this.applySession(response)),
      map((response) => response.access_token)
    );
  }

  logout(): void {
    localStorage.removeItem(this.accessTokenKey);
    localStorage.removeItem(this.refreshTokenKey);
    localStorage.removeItem(this.userKey);
    this.currentUserSubject.next(null);
  }

  isAuthenticated(): boolean {
    return !!this.getAccessToken();
  }

  getAccessToken(): string {
    return localStorage.getItem(this.accessTokenKey) || '';
  }

  getRefreshToken(): string {
    return localStorage.getItem(this.refreshTokenKey) || '';
  }

  getCurrentUser(): AuthUser | null {
    return this.currentUserSubject.value;
  }

  hasRole(...roles: string[]): boolean {
    const user = this.getCurrentUser();
    return !!user && roles.includes(user.role);
  }

  restoreSession(): Observable<boolean> {
    if (this.getAccessToken()) {
      return of(true);
    }
    if (!this.getRefreshToken()) {
      return of(false);
    }
    return this.refreshSession().pipe(
      map(() => true),
      catchError(() => {
        this.logout();
        return of(false);
      })
    );
  }

  private applySession(response: AuthTokens): void {
    localStorage.setItem(this.accessTokenKey, response.access_token);
    localStorage.setItem(this.refreshTokenKey, response.refresh_token);
    localStorage.setItem(this.userKey, JSON.stringify(response.user));
    this.currentUserSubject.next(response.user);
  }

  private readUser(): AuthUser | null {
    const raw = localStorage.getItem(this.userKey);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as AuthUser;
    } catch {
      return null;
    }
  }
}
