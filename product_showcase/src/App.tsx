import React, { useState, useEffect } from 'react';
import { 
  Activity, Shield, Zap, Map as MapIcon, 
  Settings, Database, FileText, 
  ArrowRight, BarChart3, Radio, Navigation, Clock
} from 'lucide-react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import logo from './assets/logo.jpg';

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

// --- Delhi Coordinates ---
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
  }, [center, map]);
  return null;
};

// --- View: Coming Soon ---
const ComingSoon = ({ title }: { title: string }) => (
  <div className="card glow-blue" style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
    <Clock size={64} color="var(--primary)" style={{ marginBottom: '24px', opacity: 0.5 }} />
    <h2 className="brand-name">{title}</h2>
    <p style={{ color: 'var(--on-surface-variant)', marginTop: '16px' }}>Neural Flow Intelligence Module: COMING SOON</p>
  </div>
);

function App() {
  const [view, setView] = useState('dashboard');
  const [data, setData] = useState<CityState | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/v1/ws/state';
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => setData(JSON.parse(event.data));
    return () => ws.close();
  }, []);

  const intersection = data?.intersections?.[0];

  return (
    <div className="dashboard-container">
      {/* 🧭 HEADER */}
      <header className="header">
        <div className="flex" style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <img src={logo} alt="Synapse Logo" style={{ width: '40px', height: '40px', borderRadius: '12px', objectFit: 'contain' }} />
          <h1 className="brand-name" style={{ fontSize: '20px' }}>Synapse Signal<span style={{ fontWeight: 300, fontSize: '14px', marginLeft: '8px', color: 'var(--on-surface-variant)' }}>AI Control Platform</span></h1>
        </div>

        <div className="system-status" style={{ display: 'flex', gap: '32px' }}>
          <div className="status-active">
            <div className="status-pulse" />
            <span className="pill" style={{ color: 'var(--secondary)' }}>Live Stream Active</span>
          </div>
          <div style={{ display: 'flex', gap: '16px' }}>
             <span className="pill">Region: Delhi NCR</span>
             <span className="pill">Latency: {data?.metrics?.decision_latency || 8} ms</span>
          </div>
        </div>
      </header>

      {/* 📂 SIDEBAR */}
      <aside className="sidebar">
        <div className={`nav-item ${view === 'dashboard' ? 'active' : ''}`} onClick={() => setView('dashboard')}><Activity size={20} /> Dashboard</div>
        <div className={`nav-item ${view === 'map' ? 'active' : ''}`} onClick={() => setView('map')}><MapIcon size={20} /> Live Map</div>
        <div className={`nav-item ${view === 'intersections' ? 'active' : ''}`} onClick={() => setView('intersections')}><Navigation size={20} /> Intersections</div>
        <div className={`nav-item ${view === 'emergency' ? 'active' : ''}`} onClick={() => setView('emergency')}><Shield size={20} /> Emergency Control</div>
        <div className={`nav-item ${view === 'pipeline' ? 'active' : ''}`} onClick={() => setView('pipeline')}><Database size={20} /> Pipeline</div>
        <div className={`nav-item ${view === 'analytics' ? 'active' : ''}`} onClick={() => setView('analytics')}><BarChart3 size={20} /> Analytics</div>
        <div className={`nav-item ${view === 'system' ? 'active' : ''}`} onClick={() => setView('system')}><Settings size={20} /> System</div>
        <div className={`nav-item ${view === 'logs' ? 'active' : ''}`} onClick={() => setView('logs')}><FileText size={20} /> Logs / Replay</div>
      </aside>

      {/* 📺 DYNAMIC MAIN VIEW */}
      {view === 'dashboard' || view === 'intersections' ? (
        <>
          <main className="main-map glow-blue">
            <MapContainer 
              center={DELHI_CENTER} zoom={13} 
              style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }}
              zoomControl={false}
            >
              <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" attribution='&copy; Google Maps' />
              <MapController center={DELHI_CENTER} />
              {DELHI_NODES.map(node => (
                <CircleMarker key={node.id} center={node.pos} radius={12} pathOptions={{ fillColor: node.id === 'AIIMS_CIRCLE' ? (intersection?.signal?.north_south === 'GREEN' ? '#00fd87' : '#ff716b') : '#6dddff', fillOpacity: 0.8, color: '#fff', weight: 2 }}>
                  <Popup><div style={{ padding: '8px' }}><h3 style={{ fontSize: '12px' }}>{node.name}</h3><span className="pill">Active Node</span></div></Popup>
                </CircleMarker>
              ))}
            </MapContainer>
            <div style={{ position: 'absolute', top: '24px', left: '24px', zIndex: 1000 }}><div className="glass-card" style={{ padding: '12px 20px', borderRadius: '24px' }}><span className="section-title" style={{ margin: 0, fontSize: '10px' }}>Delhi Cartographic Intelligence</span></div></div>
          </main>

          <section className="intelligence-stack">
            <div className="card">
              <h3 className="section-title">Signal Intelligence</h3>
              <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
                <div style={{ textAlign: 'center' }}><div className={`signal-marker ${intersection?.signal?.north_south === 'GREEN' ? 'glow-green' : ''}`} style={{ background: intersection?.signal?.north_south === 'GREEN' ? 'var(--secondary)' : '#333' }}><Zap size={20} color="#fff" /></div><p style={{ marginTop: '12px', fontSize: '10px', fontWeight: 800 }}>NS</p></div>
                <div style={{ textAlign: 'center' }}><div className={`signal-marker ${intersection?.signal?.east_west === 'GREEN' ? 'glow-green' : ''}`} style={{ background: intersection?.signal?.east_west === 'GREEN' ? 'var(--secondary)' : '#333' }}><Zap size={20} color="#fff" /></div><p style={{ marginTop: '12px', fontSize: '10px', fontWeight: 800 }}>EW</p></div>
              </div>
            </div>
            <div className="card glow-blue">
              <h3 className="section-title">AI Decision Reasoning</h3>
              {intersection?.decision?.reasons.map((r, i) => <p key={i} style={{ fontSize: '13px', marginBottom: '8px' }}>• {r}</p>)}
              <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'space-between' }}><span style={{ fontSize: '11px', opacity: 0.6 }}>Confidence</span><span style={{ fontWeight: 800 }}>{(intersection?.decision?.confidence || 0) * 100}%</span></div>
            </div>
            <div className="card">
              <h3 className="section-title">Delhi Node Metrics</h3>
              <div className="metric-row"><span style={{ fontSize: '12px' }}>Active Vehicles</span><span className="metric-value">{data?.metrics?.vehicle_count || 137}</span></div>
              <div className="metric-row"><span style={{ fontSize: '12px' }}>Avg Latency</span><span className="metric-value">{data?.metrics?.detection_latency || 42}ms</span></div>
            </div>
          </section>

          <footer className="bottom-panel">
            <h3 className="section-title" style={{ marginBottom: '8px' }}>Synapse Ingestion Pipeline</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              {['Capture', 'Detect', 'Track', 'Reason', 'Control'].map((s, i) => (
                <React.Fragment key={s}>
                  <div style={{ textAlign: 'center' }}><div style={{ width: '40px', height: '40px', borderRadius: '12px', background: i < 4 ? 'rgba(109,221,255,0.1)' : '#1a191b', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '4px' }}><Radio size={16} color="var(--primary)" /></div><p style={{ fontSize: '9px', fontWeight: 800 }}>{s}</p></div>
                  {i < 4 && <ArrowRight size={14} color="#333" />}
                </React.Fragment>
              ))}
            </div>
          </footer>
        </>
      ) : view === 'map' ? (
        <main className="main-map" style={{ gridColumn: '2 / 4', gridRow: '2 / 4' }}>
          <MapContainer center={DELHI_CENTER} zoom={13} style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }} zoomControl={false}>
            <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" attribution='&copy; Google Maps' />
            <MapController center={DELHI_CENTER} />
            {DELHI_NODES.map(node => (
              <CircleMarker key={node.id} center={node.pos} radius={14} pathOptions={{ fillColor: 'var(--primary)', fillOpacity: 0.6, color: '#fff', weight: 2 }} />
            ))}
          </MapContainer>
        </main>
      ) : view === 'emergency' ? (
        <main className="main-map" style={{ gridColumn: '2 / 4', gridRow: '2 / 4', display: 'grid', gridTemplateColumns: '1fr 380px', gap: '24px', background: 'transparent' }}>
           <div className="main-map" style={{ borderRadius: 'var(--radius-xl)', overflow: 'hidden' }}>
             <MapContainer center={[28.5672, 77.2100]} zoom={15} style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }}>
                <TileLayer url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}" />
                <CircleMarker center={[28.5672, 77.2100]} radius={15} pathOptions={{ fillColor: 'var(--tertiary)', fillOpacity: 0.8 }}><Popup>AIIMS Delhi</Popup></CircleMarker>
                <CircleMarker center={[28.5682, 77.2150]} radius={8} pathOptions={{ fillColor: 'var(--secondary)' }}><Popup>AMB_007 (Active)</Popup></CircleMarker>
             </MapContainer>
           </div>
           <div className="intelligence-stack">
             <div className="card glow-red">
               <h3 className="section-title">Emergency Control</h3>
               <div style={{ padding: '20px', background: 'rgba(255,113,107,0.1)', borderRadius: '24px', marginBottom: '24px' }}>
                 <p style={{ fontWeight: 800, color: 'var(--tertiary)' }}>AMBULANCE NEAR AIIMS</p>
                 <p style={{ fontSize: '12px', marginTop: '4px' }}>ETA: 45 seconds | Route Active</p>
               </div>
               <div className="metric-row"><span>Hospital Active</span><span>AIIMS Delhi</span></div>
               <div className="metric-row"><span>Override Status</span><span style={{ color: 'var(--secondary)' }}>GRANTED</span></div>
             </div>
           </div>
        </main>
      ) : view === 'pipeline' || view === 'analytics' ? (
        <main style={{ gridColumn: '2 / 4', gridRow: '2 / 4' }}>
          <div className="card glow-blue" style={{ height: '100%' }}>
            <h2 className="brand-name">Neural Pipeline Analytics</h2>
            <div style={{ marginTop: '40px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '32px' }}>
               <div className="glass-card">
                 <h3 className="section-title">Ingestion Flow</h3>
                 <p style={{ fontSize: '32px', fontWeight: 800, fontFamily: 'Space Grotesk' }}>{data?.pipeline?.detection_count || 1240}</p>
                 <p style={{ color: 'var(--on-surface-variant)' }}>Total Frames Processed</p>
               </div>
               <div className="glass-card">
                 <h3 className="section-title">Analytics Accuracy</h3>
                 <p style={{ fontSize: '32px', fontWeight: 800, fontFamily: 'Space Grotesk' }}>91.4%</p>
                 <p style={{ color: 'var(--on-surface-variant)' }}>Model Confidence</p>
               </div>
            </div>
            <div className="bottom-panel" style={{ marginTop: 'auto', background: 'var(--surface-high)' }}>
               <p style={{ fontSize: '10px', color: 'var(--on-surface-variant)' }}>PIPELINE STATUS: {data?.pipeline?.stage || 'STREAMING_SYNAPSE_CORE_V2'}</p>
            </div>
          </div>
        </main>
      ) : (
        <main style={{ gridColumn: '2 / 4', gridRow: '2 / 4' }}>
          <ComingSoon title={view.toUpperCase()} />
        </main>
      )}
    </div>
  );
}

export default App;
