import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { Router } from '@angular/router';
import { catchError, finalize, of, take, timeout } from 'rxjs';
import { AuthService } from '../../services/auth';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './login.html',
  styleUrls: ['./login.css'],
})
export class LoginComponent implements OnInit {
  readonly currentYear = new Date().getFullYear();
  username = '';
  password = '';
  loading = false;
  error = '';
  showPassword = false;

  constructor(private auth: AuthService, private router: Router, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    // Entering login should start from a clean auth state to avoid stale token loops.
    const hasToken = !!this.auth.getAccessToken() || !!this.auth.getRefreshToken();
    if (hasToken && !this.auth.getCurrentUser()) {
      this.auth.logout();
      return;
    }

    if (this.auth.isAuthenticated()) {
      const route = this.auth.hasRole('admin') ? '/dashboard' : '/invoices';
      this.router.navigateByUrl(route);
    }
  }

  submit(): void {
    if (!this.username.trim() || !this.password.trim()) {
      this.error = 'Veuillez saisir le nom d\'utilisateur et le mot de passe.';
      return;
    }

    this.loading = true;
    this.error = '';

    const request$ = this.auth.login({ username: this.username.trim(), password: this.password });

    request$
      .pipe(
        take(1),
        timeout(20000),
        catchError((err) => {
          this.error =
            err?.error?.detail ||
            'Connexion impossible. Verifiez vos identifiants ou reessayez plus tard.';
          return of(null);
        }),
        finalize(() => {
          this.loading = false;
          this.cdr.detectChanges();
        })
      )
      .subscribe((response) => {
        if (!response) {
          return;
        }
        const role = response.user?.role === 'admin' ? '/dashboard' : '/invoices';
        this.router.navigateByUrl(role);
      });
  }

  clearError(): void {
    if (this.error) {
      this.error = '';
    }
  }
}
