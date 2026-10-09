import React from 'react';
import { Database, FileDigit, Sliders, LineChart, FileSpreadsheet, PlayCircle } from 'lucide-react';

export default function SystemArchitecture() {
  return (
    <div className="view-container">
      <div className="system-flow-card">
        <h3 style={{ fontSize: '1.5rem', fontWeight: 700, textAlign: 'center', marginBottom: '1rem' }}>
          Statement Modernized Service Pipeline
        </h3>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', textAlign: 'center', maxWidth: '600px', margin: '0 auto 2rem auto', lineHeight: 1.6 }}>
          A secure, modular, asynchronous pipeline built using FastAPI, PostgreSQL/SQLite fallback data persistence, and coordinated task runner execution flow.
        </p>

        <div className="system-flow-grid">
          <div className="flow-step">
            <div className="flow-step-icon">
              <FileDigit size={32} />
            </div>
            <h4>1. PDF Preprocessing</h4>
            <p>
              Uploaded statement is saved to secure storage. The system hashes the header structures to match existing templates or triggers coordinate alignment.
            </p>
          </div>

          <div className="flow-step">
            <div className="flow-step-icon">
              <Sliders size={32} />
            </div>
            <h4>2. Agent Extraction</h4>
            <p>
              Resolves vertical coordinate lines (either via auto-detection template rules or custom coordinates) and parses tabular transaction lines.
            </p>
          </div>

          <div className="flow-step">
            <div className="flow-step-icon">
              <LineChart size={32} />
            </div>
            <h4>3. Metrics & Scoring</h4>
            <p>
              Calculates financial health indices (Average Balance, Debt/Income, Negative Months, Irregular Credits) and archives clean transaction tables.
            </p>
          </div>
        </div>

        <div style={{ marginTop: '3rem', borderTop: '1px solid var(--border-color)', paddingTop: '2rem' }}>
          <h4 style={{ fontWeight: 600, fontSize: '1.1rem', marginBottom: '1rem' }}>
            Data Schema Specifications
          </h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
            <div className="info-group">
              <h5 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Database size={16} color="#3b82f6" />
                Applications Registry
              </h5>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Stores metadata of every uploaded statement file, applicant identity details, processing states, and connection indicators.
              </p>
            </div>
            <div className="info-group">
              <h5 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <FileSpreadsheet size={16} color="#10b981" />
                Transaction Vault
              </h5>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Structured transaction ledger. Ensures full integrity, allowing downstream credit modeling and loan balance charts.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
