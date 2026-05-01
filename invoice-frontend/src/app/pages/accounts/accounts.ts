import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { Subscription, catchError, finalize, of, take, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import { AuthService } from '../../services/auth';

interface ComptableAccount {
  user_id: string;
  username: string;
  role: string;
  display_name: string;
  permissions?: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

@Component({
  selector: 'app-accounts',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './accounts.html',
  styleUrls: ['./accounts.css'],
})
export class AccountsComponent implements OnInit, OnDestroy {
  loading = true;
  saving = false;
  error = '';
  items: ComptableAccount[] = [];
  private loadSub?: Subscription;
  createPermissionsOpen = false;
  editPermissionsOpen: Record<string, boolean> = {};

  form = {
    username: '',
    display_name: '',
    password: '',
    permissions: ['save_invoice', 'ask_chat', 'modify_invoice'] as string[],
  };

  editState: Record<string, { display_name: string; password: string; is_active: boolean; permissions: string[] }> = {};

  readonly permissionOptions = [
    { value: 'all_permissions', label: 'Toutes les permissions' },
    { value: 'save_invoice', label: 'Enregistrer une facture' },
    { value: 'ask_chat', label: 'Poser une question au chat' },
    { value: 'modify_invoice', label: 'Modifier une facture' },
  ];

  readonly concretePermissions = ['save_invoice', 'ask_chat', 'modify_invoice'];

  constructor(
    private authService: AuthService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.loadComptables();
  }

  ngOnDestroy(): void {
    this.loadSub?.unsubscribe();
  }

  loadComptables(): void {
    this.loadSub?.unsubscribe();
    this.loading = true;
    this.error = '';
    this.cdr.detectChanges();

    this.loadSub = this.authService.listComptables().pipe(
      take(1),
      timeout(20000),
      catchError((err) => {
        this.items = [];
        this.error = err?.error?.detail || err?.message || 'Impossible de charger les comptes comptable.';
        return of({ count: 0, items: [] });
      }),
      finalize(() => {
        this.loading = false;
        this.cdr.detectChanges();
      })
    ).subscribe({
      next: (res) => {
        this.items = Array.isArray(res?.items) ? res.items : [];
        this.editState = {};
        this.editPermissionsOpen = {};
        for (const item of this.items) {
          this.editState[item.user_id] = {
            display_name: item.display_name || '',
            password: '',
            is_active: !!item.is_active,
            permissions: Array.isArray(item.permissions) && item.permissions.length
              ? [...item.permissions]
              : ['save_invoice', 'ask_chat', 'modify_invoice'],
          };
        }
      },
    });
  }

  createComptable(): void {
    if (!this.form.username.trim() || !this.form.display_name.trim() || this.form.password.length < 6) {
      Swal.fire('Validation', 'Nom utilisateur, nom et mot de passe (min 6) sont obligatoires.', 'warning');
      return;
    }
    if (!this.form.permissions.length) {
      Swal.fire('Validation', 'Selectionnez au moins une permission.', 'warning');
      return;
    }
    const normalizedPermissions = this.normalizeSelectedPermissions(this.form.permissions);

    this.saving = true;
    this.authService.createComptable({
      username: this.form.username.trim(),
      display_name: this.form.display_name.trim(),
      password: this.form.password,
      permissions: normalizedPermissions,
    }).subscribe({
      next: () => {
        this.saving = false;
        this.form = {
          username: '',
          display_name: '',
          password: '',
          permissions: ['save_invoice', 'ask_chat', 'modify_invoice'],
        };
        this.createPermissionsOpen = false;
        this.loadComptables();
        Swal.fire('Succes', 'Compte comptable cree.', 'success');
      },
      error: (err) => {
        this.saving = false;
        Swal.fire('Erreur', err?.error?.detail || 'Creation impossible.', 'error');
      },
    });
  }

  saveChanges(item: ComptableAccount): void {
    const state = this.editState[item.user_id];
    if (!state) return;

    const payload: { display_name?: string; password?: string; is_active?: boolean; permissions?: string[] } = {};

    if ((state.display_name || '').trim() && state.display_name !== item.display_name) {
      payload.display_name = state.display_name.trim();
    }
    if (state.password && state.password.length >= 6) {
      payload.password = state.password;
    }
    if (state.is_active !== item.is_active) {
      payload.is_active = state.is_active;
    }
    const normalizedPermissions = this.normalizeSelectedPermissions(state.permissions);
    if (!this.samePermissions(normalizedPermissions, item.permissions || [])) {
      if (!normalizedPermissions.length) {
        Swal.fire('Validation', 'Selectionnez au moins une permission.', 'warning');
        return;
      }
      payload.permissions = normalizedPermissions;
    }

    if (!Object.keys(payload).length) {
      Swal.fire('Info', 'Aucun changement a enregistrer.', 'info');
      return;
    }

    this.authService.updateComptable(item.user_id, payload).subscribe({
      next: () => {
        state.password = '';
        this.loadComptables();
        Swal.fire('Succes', 'Compte mis a jour.', 'success');
      },
      error: (err) => {
        Swal.fire('Erreur', err?.error?.detail || 'Mise a jour impossible.', 'error');
      },
    });
  }

  private samePermissions(a: string[], b: string[]): boolean {
    const left = [...(a || [])].map((x) => x.trim()).filter(Boolean).sort();
    const right = [...(b || [])].map((x) => x.trim()).filter(Boolean).sort();
    if (left.length !== right.length) return false;
    return left.every((v, i) => v === right[i]);
  }

  private normalizeSelectedPermissions(values: string[]): string[] {
    const set = new Set((values || []).map((v) => String(v || '').trim()).filter(Boolean));
    if (set.has('all_permissions')) {
      return ['save_invoice', 'ask_chat', 'modify_invoice'];
    }
    return [...set].filter((v) => ['save_invoice', 'ask_chat', 'modify_invoice'].includes(v));
  }

  isFormPermissionSelected(permission: string): boolean {
    const selected = this.form.permissions || [];
    if (permission === 'all_permissions') {
      const normalized = this.normalizeSelectedPermissions(selected);
      return this.samePermissions(normalized, this.concretePermissions);
    }
    return selected.includes(permission);
  }

  toggleFormPermission(permission: string): void {
    this.form.permissions = this.togglePermissionList(this.form.permissions, permission);
  }

  toggleCreatePermissionsDropdown(event?: MouseEvent): void {
    event?.stopPropagation();
    this.editPermissionsOpen = {};
    this.createPermissionsOpen = !this.createPermissionsOpen;
  }

  closeCreatePermissionsDropdown(): void {
    this.createPermissionsOpen = false;
  }

  isEditPermissionSelected(userId: string, permission: string): boolean {
    const state = this.editState[userId];
    if (!state) return false;
    if (permission === 'all_permissions') {
      const normalized = this.normalizeSelectedPermissions(state.permissions || []);
      return this.samePermissions(normalized, this.concretePermissions);
    }
    return (state.permissions || []).includes(permission);
  }

  toggleEditPermission(userId: string, permission: string): void {
    const state = this.editState[userId];
    if (!state) return;
    state.permissions = this.togglePermissionList(state.permissions || [], permission);
  }

  isEditPermissionsOpen(userId: string): boolean {
    return !!this.editPermissionsOpen[userId];
  }

  toggleEditPermissionsDropdown(userId: string, event?: MouseEvent): void {
    event?.stopPropagation();
    const currentlyOpen = !!this.editPermissionsOpen[userId];
    this.createPermissionsOpen = false;
    this.editPermissionsOpen = {};
    this.editPermissionsOpen[userId] = !currentlyOpen;
  }

  closeEditPermissionsDropdown(userId: string): void {
    this.editPermissionsOpen[userId] = false;
  }

  getPermissionsSummary(values: string[]): string {
    const normalized = this.normalizeSelectedPermissions(values || []);
    if (!normalized.length) {
      return 'Selectionner...';
    }
    if (this.samePermissions(normalized, this.concretePermissions)) {
      return 'Toutes les permissions';
    }
    const labels = normalized
      .map((value) => this.permissionOptions.find((opt) => opt.value === value)?.label || value)
      .filter(Boolean);
    return labels.join(' • ');
  }

  shouldOpenUp(rowIndex: number): boolean {
    // Open upward only for the very last row.
    return rowIndex === this.items.length - 1;
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement | null;
    if (!target) return;

    // Keep menu open while clicking inside permission select or its menu.
    if (target.closest('.permissions-select')) {
      return;
    }

    this.createPermissionsOpen = false;
    this.editPermissionsOpen = {};
  }

  private togglePermissionList(current: string[], permission: string): string[] {
    const base = Array.isArray(current) ? [...current] : [];

    if (permission === 'all_permissions') {
      const normalized = this.normalizeSelectedPermissions(base);
      if (this.samePermissions(normalized, this.concretePermissions)) {
        return [];
      }
      return [...this.concretePermissions];
    }

    const set = new Set(base.filter((p) => this.concretePermissions.includes(p)));
    if (set.has(permission)) {
      set.delete(permission);
    } else {
      set.add(permission);
    }
    return [...set];
  }

  deactivate(item: ComptableAccount): void {
    Swal.fire({
      title: 'Desactiver ce compte ?',
      text: `Compte ${item.username}`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Oui, desactiver',
      cancelButtonText: 'Annuler',
    }).then((result) => {
      if (!result.isConfirmed) return;
      this.authService.deactivateComptable(item.user_id).subscribe({
        next: () => {
          this.loadComptables();
          Swal.fire('Succes', 'Compte desactive.', 'success');
        },
        error: (err) => {
          Swal.fire('Erreur', err?.error?.detail || 'Desactivation impossible.', 'error');
        },
      });
    });
  }

  formatDate(value: string): string {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
  }
}
