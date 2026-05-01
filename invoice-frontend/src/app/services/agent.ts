import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from '../app.config';

export interface ChatAskResponse {
  session_id: string;
  collection: string;
  mongo_filter: Record<string, any>;
  count: number;
  answer: string;
  results: any[];
  llm_raw: string;
  pdf_generated?: boolean;
  pdf_filename?: string;
  pdf_base64?: string;
}

@Injectable({ providedIn: 'root' })
export class AgentService {

  constructor(private http: HttpClient) {}

  ask(prompt: string, sessionId: string): Observable<ChatAskResponse> {
    return this.http.post<ChatAskResponse>(`${API_URL}/chat/ask`, {
      prompt,
      session_id: sessionId,
    });
  }
}