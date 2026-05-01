import { CommonModule } from '@angular/common';
import { Component, OnInit, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { Subscription } from 'rxjs';
import { InvoiceService } from './services/invoice';
import { AuthService } from './services/auth';
import { AuthUser } from './models/auth.model';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, CommonModule, MatIconModule],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App implements OnInit, OnDestroy {
  darkMode = false;
  totalFactures = 0;
  showShell = true;
  currentUser: AuthUser | null = null;
  private countSub?: Subscription;
  private routeSub?: Subscription;
  private userSub?: Subscription;

  constructor(
    private invoiceService: InvoiceService,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit() {
    this.countSub = this.invoiceService.invoiceCount$.subscribe((count) => {
      this.totalFactures = count;
    });
    this.userSub = this.authService.currentUser$.subscribe((user) => {
      this.currentUser = user;
    });
    this.routeSub = this.router.events.subscribe((event) => {
      if (event instanceof NavigationEnd) {
        this.showShell = !event.urlAfterRedirects.startsWith('/login');
      }
    });
    this.showShell = !this.router.url.startsWith('/login');
    this.invoiceService.refreshInvoiceCount();
  }

  ngOnDestroy() {
    this.countSub?.unsubscribe();
    this.routeSub?.unsubscribe();
    this.userSub?.unsubscribe();
  }

  get isAdmin(): boolean {
    return this.authService.hasRole('admin');
  }

  toggleDark() {
    this.darkMode = !this.darkMode;
    if (this.darkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }

  logout() {
    this.authService.logout();
    this.router.navigateByUrl('/login');
  }
}
