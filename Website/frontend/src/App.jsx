import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Dashboard from './components/Dashboard';
import UploadForm from './components/UploadForm';
import InteractiveCalibrator from './components/InteractiveCalibrator';
import SystemArchitecture from './components/SystemArchitecture';
import BanksConfig from './components/BanksConfig';
import DetailsModal from './components/DetailsModal';

export default function App() {
  const [activeView, setActiveView] = useState('dashboard');
  const [selectedAppId, setSelectedAppId] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('theme') || 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const handleUploadComplete = (appId) => {
    setSelectedAppId(appId);
    setActiveView('dashboard');
  };

  const [calibratorPdf, setCalibratorPdf] = useState('');

  const handleEditInCalibrator = (pdfName) => {
    if (pdfName) setCalibratorPdf(pdfName);
    setActiveView('calibrator');
  };

  return (
    <div className="app-container">
      {/* Mobile Drawer Overlay Backdrop */}
      {mobileMenuOpen && (
        <div 
          className="sidebar-backdrop" 
          onClick={() => setMobileMenuOpen(false)} 
        />
      )}

      {/* Side Navigation */}
      <Sidebar 
        activeView={activeView} 
        setActiveView={(view) => {
          setActiveView(view);
          setMobileMenuOpen(false);
        }} 
        mobileMenuOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      {/* Main Workspace content */}
      <div className="app-content">
        <Header 
          activeView={activeView} 
          setActiveView={setActiveView} 
          theme={theme}
          toggleTheme={toggleTheme}
          mobileMenuOpen={mobileMenuOpen}
          setMobileMenuOpen={setMobileMenuOpen}
        />
        
        {activeView === 'dashboard' && (
          <Dashboard onViewDetails={(id) => setSelectedAppId(id)} />
        )}
        
        {activeView === 'upload' && (
          <UploadForm onUploadComplete={handleUploadComplete} />
        )}
        
        {activeView === 'calibrator' && (
          <InteractiveCalibrator initialPdf={calibratorPdf} />
        )}
        
        {activeView === 'config' && (
          <BanksConfig onEditInCalibrator={handleEditInCalibrator} />
        )}
        
        {activeView === 'architecture' && (
          <SystemArchitecture />
        )}
      </div>

      {/* Details Report Overlay Modal */}
      {selectedAppId && (
        <DetailsModal
          applicationId={selectedAppId}
          onClose={() => setSelectedAppId(null)}
        />
      )}
    </div>
  );
}
