import React from 'react';
import { ShieldCheck, Plus, RefreshCw, Sun, Moon, Menu } from 'lucide-react';

export default function Header({ 
  activeView, 
  setActiveView, 
  onRefresh, 
  isRefreshing, 
  theme, 
  toggleTheme,
  mobileMenuOpen,
  setMobileMenuOpen
}) {
  const pageDetails = {
    dashboard: {
      title: 'System Overview',
      subtitle: 'Real-time analytics, extraction confidence, and evaluation decision distributions.'
    },
    upload: {
      title: 'Upload Statement',
      subtitle: 'Submit PDF financial statements for automated extraction and stateful credit risk scoring.'
    },
    calibrator: {
      title: 'PDF Calibrator',
      subtitle: 'Visually annotate table bounding boxes, header positions, and bank template hashes.'
    },
    config: {
      title: 'Hashes Registry',
      subtitle: 'Inspect raw bank statement signatures, hash mapping rules, and configuration schemas.'
    },
    architecture: {
      title: 'Architecture & Pipeline',
      subtitle: 'Technical design blueprint outlining PDF ingestion, multi-agent parsing, and storage.'
    }
  };

  const current = pageDetails[activeView] || {
    title: 'Credit Engine',
    subtitle: 'Intelligent Bank Statement Processing Framework'
  };

  return (
    <header className="app-header">
      <div className="header-left">
        {setMobileMenuOpen && (
          <button 
            className="mobile-menu-toggle-btn"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            title="Toggle Menu"
          >
            <Menu size={22} />
          </button>
        )}
        <div className="header-title-group">
          <h2>{current.title}</h2>
          <p className="header-subtitle hide-on-mobile">{current.subtitle}</p>
        </div>
      </div>

      <div className="header-actions">
        {activeView === 'dashboard' && onRefresh && (
          <button 
            className="header-btn header-btn-secondary" 
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh Dashboard Data"
          >
            <RefreshCw size={15} className={isRefreshing ? 'spin' : ''} />
            <span className="hide-on-mobile">Sync</span>
          </button>
        )}

        {activeView !== 'upload' && (
          <button 
            className="header-btn header-btn-primary"
            onClick={() => setActiveView('upload')}
            title="Upload New Statement"
          >
            <Plus size={16} />
            <span className="hide-on-mobile">New Statement</span>
          </button>
        )}

        {toggleTheme && (
          <button 
            className="header-btn header-btn-secondary theme-toggle-btn"
            onClick={toggleTheme}
            title={`Switch to ${theme === 'dark' ? 'White / Light' : 'Dark'} Theme`}
          >
            {theme === 'dark' ? <Sun size={15} color="#f59e0b" /> : <Moon size={15} color="#3b82f6" />}
            <span className="hide-on-mobile">{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        )}
      </div>
    </header>
  );
}

