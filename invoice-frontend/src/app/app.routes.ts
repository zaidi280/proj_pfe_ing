import { Routes } from '@angular/router';
import { DashboardComponent } from './pages/dashboard/dashboard';
import { UploadComponent } from './pages/upload/upload';
import { InvoicesComponent } from './pages/invoices/invoices';
import { AgentComponent } from './pages/agent/agent';
import { InvoiceDetailComponent } from './pages/invoice-detail/invoice-detail';
import { LoginComponent } from './pages/login/login';
import { AuditComponent } from './pages/audit/audit';
import { AccountsComponent } from './pages/accounts/accounts';
import { adminOnlyGuard, authGuard, guestGuard } from './guards/auth.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', canActivate: [adminOnlyGuard], component: DashboardComponent },
  { path: 'login', component: LoginComponent, canActivate: [guestGuard] },
  { path: 'dashboard', component: DashboardComponent, canActivate: [adminOnlyGuard] },
  { path: 'upload', component: UploadComponent, canActivate: [authGuard] },
  { path: 'invoices', component: InvoicesComponent, canActivate: [authGuard] },
  { path: 'invoices/:id', component: InvoiceDetailComponent, canActivate: [authGuard] },
  { path: 'agent', component: AgentComponent, canActivate: [authGuard] },
  { path: 'audit', component: AuditComponent, canActivate: [adminOnlyGuard] },
  { path: 'comptables', component: AccountsComponent, canActivate: [adminOnlyGuard] },
];