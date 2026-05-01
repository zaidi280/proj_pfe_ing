import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { API_URL } from '../app.config';

@Injectable({ providedIn: 'root' })
export class InvoiceService {
  private invoiceCountSubject = new BehaviorSubject<number>(0);
  readonly invoiceCount$ = this.invoiceCountSubject.asObservable();

  constructor(private http: HttpClient) {}

  refreshInvoiceCount(): void {
    this.http.get<any[]>(`${API_URL}/invoices`).subscribe({
      next: (items) => this.invoiceCountSubject.next(Array.isArray(items) ? items.length : 0),
      error: () => {}
    });
  }

  extractInvoices(files: File[]): Observable<any> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return this.http.post(`${API_URL}/invoices/extract/batch`, formData);
  }

  listExtractions(batchId?: string): Observable<any> {
    if (!batchId) {
      return this.http.get(`${API_URL}/invoices/extractions?limit=500`);
    }
    return this.http.get(`${API_URL}/invoices/extractions?batch_id=${encodeURIComponent(batchId)}&limit=500`);
  }

  getExtraction(extractionId: string): Observable<any> {
    return this.http.get(`${API_URL}/invoices/extractions/${encodeURIComponent(extractionId)}`);
  }

  deleteExtraction(extractionId: string): Observable<any> {
    return this.http.delete(`${API_URL}/invoices/extractions/${encodeURIComponent(extractionId)}`);
  }

  saveInvoice(invoice: any, extractionId: string): Observable<any> {
    return this.http.post(`${API_URL}/invoices/save`, {
      invoice,
      extraction_id: extractionId,
    }).pipe(
      tap(() => this.refreshInvoiceCount())
    );
  }

  deleteInvoice(invoiceId: string): Observable<any> {
    return this.http.delete(`${API_URL}/invoices/${encodeURIComponent(invoiceId)}`).pipe(
      tap(() => this.refreshInvoiceCount())
    );
  }

  getInvoices(): Observable<any> {
    return this.http.get(`${API_URL}/invoices`);
  }
}