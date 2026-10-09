import React, { useEffect, useState } from 'react';
import { Chart as ChartJS, ArcElement, Tooltip, Legend, CategoryScale, LinearScale, BarElement, PieController } from 'chart.js';
import { Doughnut, Pie } from 'react-chartjs-2';
import { RefreshCw, Trash2, Eye, Building2, FileSpreadsheet } from 'lucide-react';

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale, LinearScale, BarElement, PieController);

import { BACKEND_URL } from '../apiConfig';

export default function Dashboard({ onViewDetails }) {
  const [applications, setApplications] = useState([]);
  const [supportedBanks, setSupportedBanks] = useState([
    "HDFC", "SBI", "ICICI", "Axis", "Kotak", "Bank Of India", "Bank Of Baroda", "Union Bank", "Punjab National Bank"
  ]);
  const [loading, setLoading] = useState(false);
  const [clearing, setClearing] = useState(false);

  const fetchApplications = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/applications`);
      if (response.ok) {
        const data = await response.json();
        setApplications(data.applications || []);
      }
    } catch (error) {
      console.error('Error fetching applications:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchSupportedBanks = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/banks`);
      if (response.ok) {
        const data = await response.json();
        if (data.banks && Array.isArray(data.banks)) {
          setSupportedBanks(data.banks);
        }
      }
    } catch (error) {
      console.error('Error fetching supported banks:', error);
    }
  };

  const handleClear = async () => {
    if (!window.confirm('Are you sure you want to clear all processing history?')) return;
    setClearing(true);
    try {
      const response = await fetch(`${BACKEND_URL}/applications/clear`, { method: 'POST' });
      if (response.ok) {
        setApplications([]);
      }
    } catch (error) {
      console.error('Error clearing applications:', error);
    } finally {
      setClearing(false);
    }
  };

  useEffect(() => {
    fetchApplications();
    fetchSupportedBanks();
  }, []);

  // Compute Metrics
  const totalStatements = applications.length;
  const processedSuccess = applications.filter((app) => app.status === 'success').length;
  const successRate = totalStatements > 0 ? ((processedSuccess / totalStatements) * 100).toFixed(0) : '0';
  
  // Calculate average confidence score
  const validScores = applications.filter((app) => app.confidence_score !== null).map((app) => app.confidence_score);
  const avgConfidence = validScores.length > 0 ? ((validScores.reduce((a, b) => a + b, 0) / validScores.length) * 100).toFixed(0) : '0';

  // Decisions Doughnut Data
  const decisionCounts = applications.reduce((acc, app) => {
    const dec = app.decision || 'pending';
    acc[dec] = (acc[dec] || 0) + 1;
    return acc;
  }, {});

  const doughnutData = {
    labels: ['Success', 'Failed', 'Pending/Processing'],
    datasets: [
      {
        data: [
          decisionCounts['extracted'] || decisionCounts['success'] || 0,
          decisionCounts['failed'] || 0,
          (decisionCounts['pending'] || 0) + (decisionCounts['processing'] || 0),
        ],
        backgroundColor: ['#10b981', '#ef4444', '#f59e0b'],
        borderColor: '#000000',
        borderWidth: 2,
      },
    ],
  };

  // Supported Banks Pie Chart Data & Ratios
  const bankCounts = supportedBanks.reduce((acc, bank) => {
    acc[bank] = 0;
    return acc;
  }, {});

  applications.forEach((app) => {
    const rawName = (app.bank_name || '').trim();
    const matched = supportedBanks.find(b => b.toLowerCase() === rawName.toLowerCase());
    if (matched) {
      bankCounts[matched] = (bankCounts[matched] || 0) + 1;
    } else {
      bankCounts['Other'] = (bankCounts['Other'] || 0) + 1;
    }
  });

  const displayBankList = [...supportedBanks];
  if (bankCounts['Other'] && !displayBankList.includes('Other')) {
    displayBankList.push('Other');
  }

  const pieLabels = displayBankList.map((bank) => {
    const count = bankCounts[bank] || 0;
    const pct = totalStatements > 0 ? ((count / totalStatements) * 100).toFixed(1) : '0.0';
    return `${bank}: ${count} (${pct}%)`;
  });

  const pieValues = displayBankList.map((bank) => bankCounts[bank] || 0);

  const bankColors = [
    '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#a855f7',
    '#06b6d4', '#f97316', '#6366f1', '#84cc16', '#64748b'
  ];

  const bankPieData = {
    labels: pieLabels,
    datasets: [
      {
        data: pieValues,
        backgroundColor: bankColors.slice(0, displayBankList.length),
        borderColor: '#000000',
        borderWidth: 2,
      },
    ],
  };

  return (
    <div className="view-container">
      {/* Metrics Row */}
      <div className="dashboard-metrics">
        <div className="metric-card">
          <div className="metric-title">Total Statements</div>
          <div className="metric-value">{totalStatements}</div>
          <div className="metric-sub success">Uploaded & Processed</div>
        </div>
        <div className="metric-card">
          <div className="metric-title">Supported Banks</div>
          <div className="metric-value">{supportedBanks.length}</div>
          <div className="metric-sub success">Template Registries Active</div>
        </div>
        {/* This is deterministic_pct -- the share of transactions categorised by
            a rule rather than by the model. It says nothing about whether the
            amounts were read out of the PDF correctly, so calling it
            "Extraction accuracy" invited exactly the wrong conclusion: a
            statement with its debit and credit columns swapped still scores
            100% here. Extraction fidelity is a separate measure. */}
        <div className="metric-card">
          <div className="metric-title">Avg Classification Coverage</div>
          <div className="metric-value">{avgConfidence}%</div>
          <div className="metric-sub success">Categorised by rule, not model</div>
        </div>
        <div className="metric-card">
          <div className="metric-title">Success Rate</div>
          <div className="metric-value">{successRate}%</div>
          <div className="metric-sub success">Parsed statements</div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="dashboard-charts">
        <div className="chart-card">
          <div className="chart-header">Pipeline Decision Distribution</div>
          <div className="chart-wrapper">
            <Doughnut
              data={doughnutData}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: {
                    position: 'bottom',
                    labels: {
                      color: 'var(--text-muted)',
                      boxWidth: 12,
                      padding: 10,
                      font: { size: 11 }
                    }
                  }
                }
              }}
            />
          </div>
        </div>
        <div className="chart-card">
          <div className="chart-header">Supported Banks Statement Distribution</div>
          <div className="chart-wrapper">
            <Pie
              data={bankPieData}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: {
                    position: 'bottom',
                    labels: {
                      color: 'var(--text-muted)',
                      boxWidth: 10,
                      padding: 8,
                      font: { size: 10 }
                    }
                  },
                  tooltip: {
                    callbacks: {
                      label: (context) => ` ${context.label}`
                    }
                  }
                }
              }}
            />
          </div>
        </div>
      </div>

      {/* Historical List Card */}
      <div className="table-card">
        <div className="table-header">
          <h3>Recent Applications</h3>
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button className="clear-btn" style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', border: '1.5px solid #000000' }} onClick={fetchApplications}>
              <RefreshCw size={14} style={{ marginRight: '0.25rem' }} />
              <span className="hide-on-mobile">Refresh</span>
            </button>
            <button className="clear-btn" style={{ border: '1.5px solid #000000' }} onClick={handleClear} disabled={clearing}>
              <Trash2 size={14} style={{ marginRight: '0.25rem' }} />
              <span className="hide-on-mobile">Clear All</span>
            </button>
          </div>
        </div>
        
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Applicant Name</th>
                <th>Bank Name</th>
                <th>Upload Date</th>
                <th>Avg Balance</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    Loading database records...
                  </td>
                </tr>
              ) : applications.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    No bank statements found. Go to 'Upload Statement' to process a file.
                  </td>
                </tr>
              ) : (
                applications.map((app) => (
                  <tr key={app.id}>
                    <td style={{ fontWeight: 600 }}>{app.applicant_name}</td>
                    <td>{app.bank_name}</td>
                    <td>{new Date(app.created_at).toLocaleString()}</td>
                    <td>₹ {app.average_monthly_balance ? app.average_monthly_balance.toFixed(2) : '0.00'}</td>
                    <td>
                      <span className={`status-badge ${app.status}`}>
                        {app.status}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                        <button
                          className="action-link"
                          style={{ background: 'transparent', border: 'none', display: 'flex', alignItems: 'center', gap: '0.25rem' }}
                          onClick={() => onViewDetails(app.id)}
                          title="View Report"
                        >
                          <Eye size={16} />
                          <span className="hide-on-mobile">View Report</span>
                        </button>
                        {app.status === 'completed' && (
                          <button
                            className="action-link"
                            style={{ background: 'transparent', border: 'none', display: 'flex', alignItems: 'center', gap: '0.25rem', color: '#16a34a' }}
                            onClick={() => window.open(`${BACKEND_URL}/report-cam/${app.id}/download`, '_blank')}
                            title="Export Credit Appraisal Memo (CAM Report)"
                          >
                            <FileSpreadsheet size={16} />
                            <span className="hide-on-mobile">CAM Report</span>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
