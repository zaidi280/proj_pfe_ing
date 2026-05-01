import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, ChangeDetectorRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { Subscription, catchError, finalize, of, take, timeout } from 'rxjs';
import { AuditItem, AuditService } from '../../services/audit';

@Component({
  selector: 'app-audit',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './audit.html',
  styleUrls: ['./audit.css'],
})
export class AuditComponent implements OnInit {
  items: AuditItem[] = [];
  loading = true;
  error = '';
  usernameFilter = '';
  actionFilter = '';
  actionKindFilter = '';
  fromDate = '';
  toDate = '';
  expanded: Record<string, boolean> = {};
  private loadSub?: Subscription;
  currentPage = 1;
  pageSize: number = 20;
  totalItems = 0;

  readonly actionOptions: Array<{ value: string; label: string }> = [
    { value: '', label: 'Toutes les actions' },
    { value: 'platform_access', label: 'Acces plateforme' },
    { value: 'invoice_extract_batch', label: 'Extraction de factures' },
    { value: 'invoice_saved', label: 'Enregistrement facture' },
    { value: 'invoice_updated', label: 'Modification facture' },
    { value: 'invoice_deleted', label: 'Suppression facture' },
    { value: 'chat_ask', label: 'Question Agent IA' },
  ];

  constructor(
    private auditService: AuditService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.loadAudit(true);
  }

  ngOnDestroy(): void {
    this.loadSub?.unsubscribe();
  }

  loadAudit(resetPage = false): void {
    if (resetPage) {
      this.currentPage = 1;
    }

    if (this.fromDate && this.toDate && this.fromDate > this.toDate) {
      this.error = 'La date "Du" doit etre inferieure ou egale a la date "Au".';
      this.loading = false;
      this.cdr.detectChanges();
      return;
    }

    this.loadSub?.unsubscribe();
    this.loading = true;
    this.error = '';
    this.cdr.detectChanges();

    this.loadSub = this.auditService
      .getComptableAudit(
        this.normalizedPageSize(),
        this.pageOffset(),
        this.usernameFilter,
        this.actionFilter,
        this.actionKindFilter,
        this.fromDate,
        this.toDate,
      )
      .pipe(
        take(1),
        timeout(20000),
        catchError((err) => {
          this.error = err?.error?.detail || err?.message || 'Impossible de charger l\'audit trail.';
          this.items = [];
          this.totalItems = 0;
          return of({ count: 0, total: 0, offset: 0, limit: this.normalizedPageSize(), items: [] });
        }),
        finalize(() => {
          this.loading = false;
          this.cdr.detectChanges();
        })
      )
      .subscribe({
      next: (response) => {
        this.items = Array.isArray(response?.items) ? response.items : [];
        this.totalItems = Number(response?.total || 0);
      },
      });
  }

  resetFilters(): void {
    this.usernameFilter = '';
    this.actionFilter = '';
    this.actionKindFilter = '';
    this.fromDate = '';
    this.toDate = '';
    this.loadAudit(true);
  }

  pageOffset(): number {
    return (this.currentPage - 1) * this.normalizedPageSize();
  }

  totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.normalizedPageSize()));
  }

  pages(): number[] {
    const total = this.totalPages();
    const current = this.currentPage;
    const values: number[] = [];
    let start = Math.max(1, current - 2);
    let end = Math.min(total, current + 2);

    if (end - start < 4) {
      if (start === 1) {
        end = Math.min(total, 5);
      } else {
        start = Math.max(1, total - 4);
      }
    }

    for (let i = start; i <= end; i++) {
      values.push(i);
    }
    return values;
  }

  goToPage(page: number): void {
    if (page < 1 || page > this.totalPages() || page === this.currentPage) {
      return;
    }
    this.currentPage = page;
    this.loadAudit(false);
  }

  prevPage(): void {
    this.goToPage(this.currentPage - 1);
  }

  nextPage(): void {
    this.goToPage(this.currentPage + 1);
  }

  onPageSizeChange(value: number | string): void {
    const parsed = Number(value);
    this.pageSize = Number.isFinite(parsed) && parsed > 0 ? parsed : 20;
    this.currentPage = 1;
    this.loadAudit(false);
  }

  private normalizedPageSize(): number {
    const parsed = Number(this.pageSize);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 20;
  }

  toggleRow(itemId: string): void {
    this.expanded[itemId] = !this.expanded[itemId];
  }

  isExpanded(itemId: string): boolean {
    return !!this.expanded[itemId];
  }

  formatDate(value: string): string {
    if (!value) {
      return '—';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
  }

  stringifyValue(value: any): string {
    if (value === null || value === undefined || value === '') {
      return '—';
    }
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }
    return String(value);
  }

  actionLabel(action: string): string {
    const key = (action || '').trim();
    const found = this.actionOptions.find((opt) => opt.value === key);
    return found?.label || key || 'Action inconnue';
  }

  resumeLabel(item: AuditItem): string {
    const actor = item.actor?.display_name || item.actor?.username || 'L\'utilisateur';
    const invoiceNumber = this.stringifyValue(item.metadata?.['invoice_number']);
    const extractionId = this.stringifyValue(item.metadata?.['extraction_id']);
    const path = item.request?.path || '';

    switch ((item.action || '').trim()) {
      case 'invoice_updated':
        return `${actor} a modifie la facture ${invoiceNumber !== '—' ? invoiceNumber : item.entity?.id || ''}.`;
      case 'invoice_saved':
        return `${actor} a ajoute une facture${invoiceNumber !== '—' ? ` (${invoiceNumber})` : ''}${extractionId !== '—' ? ` depuis l'extraction ${extractionId}` : ''}.`;
      case 'invoice_deleted':
        return `${actor} a supprime la facture ${invoiceNumber !== '—' ? invoiceNumber : item.entity?.id || ''}.`;
      case 'invoice_extract_batch': {
        const successCount = this.stringifyValue(item.metadata?.['success_count']);
        const totalCount = this.stringifyValue(item.metadata?.['total']);
        return `${actor} a lance une extraction de factures (${successCount}/${totalCount}).`;
      }
      case 'chat_ask':
        return `${actor} a pose une question a l'agent IA.`;
      case 'platform_access':
        return item.action_kind === 'read'
          ? `${actor} a consulte ${path || 'une ressource'}.`
          : `${actor} a effectue une action sur ${path || 'une ressource'}.`;
      default:
        return item.summary || `${actor} a effectue une action.`;
    }
  }
}
