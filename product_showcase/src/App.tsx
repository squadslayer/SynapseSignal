import React, { useState, useEffect } from 'react';
import { 
	Activity, Shield, Map as MapIcon, 
  Settings, ArrowRight, BarChart3, Radio, Clock, Database
} from 'lucide-react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap, Polyline } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import logo from './assets/logo.jpg';
import pipelineViz from './assets/pipeline_viz.png'; // 🖼️ New custom visualization

// --- Types ---
interface TrafficLane {
  lane_id: string;
  in_density: number;
  flow_score: number;
}

interface Intersection {
  id: string;
  lanes: TrafficLane[];
  signal: {
    north_south: string;
    east_west: string;
    mode: string;
  };
  decision: {
    reasons: string[];
    confidence: number;
  };
}

interface EmergencyState {
  active: boolean;
  vehicle_id: string;
  estimated_arrival_sec: number;
  priority: number;
}

interface CityState {
  timestamp: string;
  intersections: Intersection[];
  emergency: EmergencyState;
  metrics: {
    vehicle_count: number;
    decision_latency: number;
    tracking_accuracy: number;
    detection_latency: number;
  };
  pipeline: {
    detection_count: number;
    tracking_ids: number;
    stage: string;
    decision: string;
  };
}

// --- Delhi Constants ---
const DELHI_CENTER: [number, number] = [28.6139, 77.2090];
const DELHI_NODES = [
  { id: 'AIIMS_CIRCLE', pos: [28.5672, 77.2100] as [number, number], name: 'AIIMS Circle' },
  { id: 'DHAULA_KUAN', pos: [28.5918, 77.1616] as [number, number], name: 'Dhaula Kuan' },
  { id: 'TILAK_MARG', pos: [28.6163, 77.2367] as [number, number], name: 'Tilak Marg' },
];

const MapController = ({ center }: { center: [number, number] }) => {
  const map = useMap();
  useEffect(() => {
    map.setView(center);
    setTimeout(() => map.invalidateSize(), 150);
  }, [center, map]);
  return null;
};

// --- Helper: Control Panel ---
const ControlPanel = ({ onOverride, onReset, overriding }: { onOverride: () => void, onReset: () => void, overriding: boolean }) => (
  <div className="control-group">
    <button 
      className={`btn-primary ${overriding ? 'glow-red' : ''}`} 
      onClick={onOverride}
      disabled={overriding}
      style={{ 
        background: overriding ? 'var(--tertiary)' : '#f4662d',
        opacity: overriding ? 0.8 : 1,
        cursor: overriding ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '12px'
      }}
    >
      {overriding ? (
        <>
          <div className="status-pulse" style={{ background: '#fff', width: '12px', height: '12px' }} />
          ENGAGING OVERDRIVE...
        </>
      ) : 'Engage Overdrive'}
    </button>
    <button className="btn-secondary" onClick={onReset}>Reset Neural Flow</button>
  </div>
);

// --- Component: Sidebar Widget ---
const DataSidebar = ({ data, intersection, onOverride, onReset, overriding }: { data: CityState | null, intersection: Intersection | undefined, onOverride: () => void, onReset: () => void, overriding: boolean }) => (
  <aside className="data-sidebar">
    <div className="sidebar-header">
      <h2 className="brand-name">Data sidebar</h2>
      <div className="pill" style={{ background: 'rgba(109,221,255,0.1)', color: 'var(--primary)' }}>Live Feed</div>
    </div>

    <div className="data-group">
      <div className="metric-row"><span className="data-label">Intersection</span><span style={{ fontWeight: 800 }}>{intersection?.id || 'INT_001'}</span></div>
      <div className="metric-row"><span className="data-label">Status</span><span style={{ color: 'var(--secondary)' }}>Active</span></div>
    </div>

    <div className="data-group glass-card" style={{ padding: '20px', borderRadius: '24px' }}>
      <p className="data-label" style={{ marginBottom: '12px' }}>Signal Decision</p>
      <div className="metric-row"><span>N-S Status</span><span style={{ color: intersection?.signal?.north_south === 'GREEN' ? 'var(--secondary)' : 'var(--tertiary)' }}>{intersection?.signal?.north_south || 'RED'}</span></div>
      <div className="metric-row"><span>E-W Status</span><span style={{ color: intersection?.signal?.east_west === 'GREEN' ? 'var(--secondary)' : 'var(--tertiary)' }}>{intersection?.signal?.east_west || 'RED'}</span></div>
    </div>

    <div className="data-group">
      <p className="data-label">Bottleneck Analytics</p>
      <div className="metric-row"><span>Avg Speed</span><span>{data?.metrics?.decision_latency || 42} km/h</span></div>
      <div className="metric-row"><span>Queue Load</span><span style={{ color: 'var(--primary)' }}>High</span></div>
    </div>

    <ControlPanel onOverride={onOverride} onReset={onReset} overriding={overriding} />
  </aside>
);

const ComingSoon = ({ title }: { title: string }) => (
  <div className="card glow-blue" style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
    <Clock size={64} color="var(--primary)" style={{ marginBottom: '24px', opacity: 0.5 }} />
    <h2 className="brand-name">{title}</h2>
    <p style={{ color: 'var(--on-surface-variant)', marginTop: '16px' }}>Neural Flow Module: COMING SOON</p>
  </div>
);

function App() {
  const [view, setView] = useState('dashboard');
  const [data, setData] = useState<CityState | null>(null);
  const [connected, setConnected] = useState(false);
  const [overriding, setOverriding] = useState(false);

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/v1/ws/state';
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => setData(JSON.parse(event.data));
    return () => ws.close();
  }, []);

  const intersection = data?.intersections?.[0];

  const handleOverride = async () => {
    setOverriding(true);
    try {
      const response = await fetch("http://localhost:8000/api/v1/signal/override", { method: "POST" });
      if (response.ok) setTimeout(() => setOverriding(false), 3000);
    } catch (e) {
      setOverriding(false);
    }
  };

  const handleReset = () => console.log("System Reset");

  return (
    <div className="dashboard-container">
      {/* 📂 NAVIGATION SIDEBAR */}
      <aside className="sidebar">
        <div className={`nav-item ${view === 'dashboard' ? 'active' : ''}`} onClick={() => setView('dashboard')}><Activity size={20} /> Dashboard</div>
        <div className={`nav-item ${view === 'map' ? 'active' : ''}`} onClick={() => setView('map')}><MapIcon size={20} /> Live Map</div>
        <div className={`nav-item ${view === 'emergency' ? 'active' : ''}`} onClick={() => setView('emergency')}><Shield size={20} /> Emergency</div>
        <div className={`nav-item ${view === 'pipeline' ? 'active' : ''}`} onClick={() => setView('pipeline')}><Database size={20} /> Pipeline</div>
        <div className={`nav-item ${view === 'analytics' ? 'active' : ''}`} onClick={() => setView('analytics')}><BarChart3 size={20} /> Analytics</div>
        <div className={`nav-item ${view === 'system' ? 'active' : ''}`} onClick={() => setView('system')}><Settings size={20} /> System</div>
      </aside>

      {/* 📺 DYNAMIC MAIN AREA */}
      {view === 'dashboard' ? (
        <main className="main-map glow-blue">
          <MapContainer center={DELHI_CENTER} zoom={13} style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }} zoomControl={false}>
            <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" attribution='&copy; Google Maps' />
            <MapController center={DELHI_CENTER} />
            {DELHI_NODES.map(node => (
              <CircleMarker key={node.id} center={node.pos} radius={12} pathOptions={{ fillColor: node.id === 'AIIMS_CIRCLE' && intersection?.signal?.north_south === 'GREEN' ? '#00fd87' : '#ff716b', fillOpacity: 0.8, color: '#fff', weight: 2 }}><Popup>{node.name}</Popup></CircleMarker>
            ))}
          </MapContainer>
        </main>
      ) : view === 'map' ? (
        <main className="main-map" style={{ gridColumn: '1 / 4', gridRow: '1 / 3', margin: '-32px' }}>
          <MapContainer center={DELHI_CENTER} zoom={12} style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }} zoomControl={false}>
            <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" />
            <MapController center={DELHI_CENTER} />
            {DELHI_NODES.map(node => (
              <CircleMarker key={node.id} center={node.pos} radius={14} pathOptions={{ fillColor: 'var(--primary)', fillOpacity: 0.6, color: '#fff', weight: 2 }} />
            ))}
          </MapContainer>
          {/* Overlay Navigation for Full Screen Map */}
          <div style={{ position: 'absolute', top: '48px', left: '48px', zIndex: 1000, display: 'flex', gap: '16px' }}>
            <div className="nav-item active" style={{ background: 'var(--surface-low)', backdropFilter: 'blur(20px)' }} onClick={() => setView('dashboard')}>
              <Activity size={20} /> Exit Full Screen
            </div>
          </div>
        </main>
      ) : view === 'emergency' ? (
        <main className="main-map glow-red">
          <MapContainer center={[28.5672, 77.2100]} zoom={15} style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }} zoomControl={false}>
            <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" />
            <MapController center={[28.5672, 77.2100]} />
            <CircleMarker center={[28.5672, 77.2100]} radius={15} pathOptions={{ fillColor: 'var(--tertiary)', fillOpacity: 0.8, color: '#fff', weight: 3 }}><Popup>AIIMS Delhi</Popup></CircleMarker>
            <CircleMarker center={[28.5610, 77.2045]} radius={12} pathOptions={{ fillColor: 'var(--secondary)', fillOpacity: 0.9, color: '#fff', weight: 2 }}><Popup>AMBULANCE Status: IN_TRANSIT</Popup></CircleMarker>
            <Polyline 
              positions={[
                [28.5610, 77.2045], // Aurobindo Marg S
                [28.5625, 77.2054], // Curve 1
                [28.5644, 77.2064], // Curve 2
                [28.5656, 77.2070], // Ring Rd Intersection
                [28.5668, 77.2081], // Admission Entrance
                [28.5670, 77.2092], // Internal Rd
                [28.5672, 77.2100]  // Critical Area
              ]} 
              pathOptions={{ color: 'var(--secondary)', weight: 10, opacity: 0.5, lineCap: 'round', lineJoin: 'round' }} 
            />
          </MapContainer>
        </main>
      ) : view === 'pipeline' ? (
        <main style={{ gridColumn: '2 / 4', gridRow: '1 / 3' }}>
           <div className="card" style={{ height: '100%', overflow: 'hidden', padding: 0, position: 'relative' }}>
              <img src={pipelineViz} alt="Pipeline Viz" style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.8 }} />
              <div style={{ position: 'absolute', top: '40px', left: '40px', maxWidth: '400px' }}>
                <h2 className="brand-name" style={{ fontSize: '32px', marginBottom: '16px' }}>Neural Architecture</h2>
                <div className="glass-card" style={{ padding: '24px' }}>
                  <p className="data-label">Pipeline Load</p>
                  <p style={{ fontSize: '24px', fontWeight: 600 }}>0.48 ms Latency</p>
                </div>
              </div>
           </div>
        </main>
      ) : (
        <ComingSoon title={view.toUpperCase()} />
      )}

      {/* 📊 DATA SIDEBAR */}
      {view === 'dashboard' && <DataSidebar data={data} intersection={intersection} onOverride={handleOverride} onReset={handleReset} overriding={overriding} />}
      
      {view === 'emergency' && (
        <aside className="data-sidebar">
           <div className="sidebar-header">
              <h2 className="brand-name">Emergency stack</h2>
              <div className="pill" style={{ background: 'rgba(255,113,107,0.1)', color: 'var(--tertiary)' }}>Priority Alpha</div>
           </div>
           <div className="data-group glass-card glow-red" style={{ padding: '24px', borderRadius: '32px' }}>
             <h3 className="section-title" style={{ color: 'var(--tertiary)' }}>Active Incident</h3>
             <p style={{ fontWeight: 800 }}>AMBULANCE NEAR AIIMS</p>
             <p style={{ fontSize: '12px', opacity: 0.7 }}>ETA: 45 seconds | Route Active</p>
             <div style={{ marginTop: '12px' }}>
               <div className="metric-row"><span>Hospital</span><span>AIIMS Delhi</span></div>
               <div className="metric-row"><span>Signal Override</span><span style={{ color: 'var(--secondary)' }}>GRANTED</span></div>
             </div>
           </div>
           <div className="data-group">
              <p className="data-label">Nodes cleared</p>
              <div className="metric-row"><span>INT_001</span><span>0 SEC WAIT</span></div>
           </div>
           <ControlPanel onOverride={handleOverride} onReset={handleReset} overriding={overriding} />
        </aside>
      )}

      {/* 🛣️ PIPELINE FOOTER (DASHBOARD/EMERGENCY) */}
      {(view === 'dashboard' || view === 'emergency') && (
        <footer className="bottom-panel">
          <h3 className="section-title" style={{ marginBottom: '8px' }}>Neural Ingestion Pipeline</h3>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {['Capture', 'Detect', 'Track', 'Reason', 'Control'].map((s, i) => (
              <React.Fragment key={s}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ width: '40px', height: '40px', borderRadius: '12px', background: i < 4 ? 'rgba(109,221,255,0.1)' : '#1a191b', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '4px' }}><Radio size={16} color="var(--primary)" /></div>
                  <p style={{ fontSize: '9px', fontWeight: 800 }}>{s}</p>
                </div>
                {i < 4 && <ArrowRight size={14} color="#333" />}
              </React.Fragment>
            ))}
          </div>
        </footer>
      )}

      {/* 🧭 SYSTEM STATUS BAR (GLOBAL BOTTOM) */}
      <header className="header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
          <img src={logo} alt="Synapse Logo" style={{ width: '360px', height: '90px', borderRadius: '24px', objectFit: 'contain', opacity: 0.85, filter: 'brightness(1.1)', background: 'var(--surface-low)' }} />
        </div>
        <div style={{ display: 'flex', gap: '32px' }}>
          <div className="status-active">
            <div className={connected ? "status-pulse" : ""} style={{ background: connected ? "var(--secondary)" : "#ff716b" }} />
            <span className="pill" style={{ color: connected ? "var(--secondary)" : "#ff716b" }}>{connected ? 'Neural Link Active' : 'Disconnected'}</span>
          </div>
          <div style={{ display: 'flex', gap: '16px' }}>
             <span className="pill">Delhi NCR</span>
             <span className="pill">Latency: {data?.metrics?.decision_latency || 8} ms</span>
          </div>
        </div>
      </header>
    </div>
  );
}

export default App;
