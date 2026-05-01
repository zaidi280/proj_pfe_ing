import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from '../app.config';

export interface AuditChange {
  field: string;
  old: any;
  new: any;
}

export interface AuditItem {
  id: string;
  actor: {
    user_id: string;
    username: string;
    role: string;
    display_name: string;
  };
  action: string;
  action_kind: 'read' | 'write' | string;
  occurred_at: string;
  request: {
    method: string;
    path: string;
    client_ip: string;
  };
  entity: {
    type: string;
    id: string;
  };
  summary: string;
  changes: AuditChange[];
  metadata: Record<string, any>;
}

export interface AuditResponse {
  count: number;
  total: number;
  offset: number;
  limit: number;
  items: AuditItem[];
}

@Injectable({ providedIn: 'root' })
export class AuditService {
  constructor(private http: HttpClient) {}

  getComptableAudit(
    limit = 50,
    offset = 0,
    username = '',
    action = '',
    actionKind = '',
    fromDate = '',
    toDate = ''
  ): Observable<AuditResponse> {
    let params = new HttpParams()
      .set('limit', String(limit))
      .set('offset', String(offset));
    if (username.trim()) {
      params = params.set('username', username.trim());
    }
    if (action.trim()) {
      params = params.set('action', action.trim());
    }
    if (actionKind.trim()) {
      params = params.set('action_kind', actionKind.trim());
    }
    if (fromDate.trim()) {
      params = params.set('from_date', fromDate.trim());
    }
    if (toDate.trim()) {
      params = params.set('to_date', toDate.trim());
    }

    return this.http.get<AuditResponse>(`${API_URL}/audit/comptable`, { params });
  }
}
