import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, from, firstValueFrom, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth';

let refreshInFlight: Promise<string> | null = null;

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const skipAuth = req.url.includes('/auth/login') || req.url.includes('/auth/register') || req.url.includes('/auth/refresh');
  const token = auth.getAccessToken();
  const authReq = !skipAuth && token
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : req;

  return next(authReq).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401 || skipAuth) {
        return throwError(() => error);
      }

      const refreshToken = auth.getRefreshToken();
      if (!refreshToken) {
        auth.logout();
        router.navigateByUrl('/login');
        return throwError(() => error);
      }

      if (!refreshInFlight) {
        refreshInFlight = firstValueFrom(auth.refreshSession()).finally(() => {
          refreshInFlight = null;
        });
      }

      return from(refreshInFlight ?? Promise.reject(new Error('Refresh failed'))).pipe(
        switchMap((newAccessToken) => {
          const retried = req.clone({ setHeaders: { Authorization: `Bearer ${newAccessToken}` } });
          return next(retried);
        }),
        catchError((refreshError) => {
          auth.logout();
          router.navigateByUrl('/login');
          return throwError(() => refreshError);
        })
      );
    })
  );
};
