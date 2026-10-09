import React from 'react';
import { LayoutDashboard, Upload, Sliders, Cpu, FileJson, X } from 'lucide-react';

export default function Sidebar({ activeView, setActiveView, mobileMenuOpen, onCloseMobile }) {
  const menuItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'upload', label: 'Upload Statement', icon: Upload },
    { id: 'calibrator', label: 'Interactive Calibrator', icon: Sliders },
    { id: 'config', label: 'Registries JSON', icon: FileJson },
    { id: 'architecture', label: 'System Architecture', icon: Cpu },
  ];

  return (
    <aside className={`app-sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <Cpu size={20} color="white" />
        </div>
        <h1>Bank Statement</h1>
        {onCloseMobile && (
          <button className="mobile-sidebar-close" onClick={onCloseMobile} title="Close Menu">
            <X size={20} />
          </button>
        )}
      </div>

      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? 'active' : ''}`}
              onClick={() => setActiveView(item.id)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
