import React, { useState, useEffect } from 'react';
import { Activity, ShieldAlert, Cpu, Map as MapIcon, Zap, Radio, Boxes } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// --- Types ---
interface Lane {
  lane_id: string;
  flow_score: number;
}

interface Signal {
  north_south: string;
  east_west: string;
  mode: string;
}

interface Intersection {
  id: string;
  lanes: Lane[];
  signal: Signal;
}

interface Emergency {
  active: boolean;
  estimated_arrival_sec: number;
}

interface CityState {
  timestamp: string;
  intersections: Intersection[];
  emergency: Emergency;
}

// --- Internal Components ---

const StatusBadge = ({ active, label, color, icon: Icon }: { active: boolean, label: string, color: string, icon: any }) => (
  <div className={`status-badge ${active ? 'pulse-active' : ''}`} style={{ borderColor: active ? `${color}4D` : 'rgba(255,255,255,0.1)', background: active ? `${color}1A` : 'rgba(255,255,255,0.05)', color: active ? color : '#ADAAAB' }}>
    <Icon size={14} />
    {label}
  </div>
);

const SignalIndicator = ({ state, label }: { state: string, label: string }) => {
  const isGreen = state === 'GREEN';
  return (
    <div className="signal-node">
      <div className={`signal-bulb ${isGreen ? 'bulb-green' : 'bulb-red'}`}>
        <Zap size={32} color={isGreen ? '#004D29' : '#4D0000'} />
      </div>
      <span className="signal-label">{label}</span>
      <span style={{ fontSize: '18px', fontWeight: 800, color: isGreen ? '#00FF88' : '#FF4D4D' }}>
        {state}
      </span>
    </div>
  );
};

const MapController = ({ center }: { center: [number, number] }) => {
  const map = useMap();
  useEffect(() => {
    map.setView(center, map.getZoom());
  }, [center, map]);
  return null;
};

export default function App() {
  const [state, setState] = useState<CityState | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/api/v1/ws/state');

    ws.onopen = () => {
      console.log('Connected to SynapseSignal WebSocket');
      setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setState(data);
      } catch (err) {
        console.error('Error parsing WS data:', err);
      }
    };

    ws.onclose = () => {
      setConnected(false);
    };

    return () => ws.close();
  }, []);

  if (!state) {
    return (
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0A0A0B', gap: '20px' }}>
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: "linear" }}>
          <Boxes color="#6DDDFF" size={48} />
        </motion.div>
        <p style={{ color: '#ADAAAB', textTransform: 'uppercase', letterSpacing: '0.2em', fontSize: '12px' }}>Initializing Neural Flow...</p>
      </div>
    );
  }

  const intersection = state.intersections[0] || null;
  const mapCenter: [number, number] = [21.1458, 79.0882]; 

  return (
    <div className="dashboard-container">
      
      {/* --- HEADER --- */}
      <header className="dashboard-header">
        <div>
          <h1 style={{ fontSize: '48px', display: 'flex', alignItems: 'center', gap: '16px' }}>
            <Cpu size={40} color="#6DDDFF" />
            SYNAPSE <span style={{ fontWeight: 300, color: '#ADAAAB' }}>SIGNAL</span>
          </h1>
          <p style={{ color: '#ADAAAB', fontSize: '14px', marginTop: '4px', fontWeight: 500 }}>
            CITY-SCALE TRAFFIC INTELLIGENCE ENGINE
          </p>
        </div>
        
        <div className="badge-container">
          <StatusBadge active={connected} label="LIVE-STREAM ACTIVE" color="#6DDDFF" icon={Radio} />
          {state.emergency.active && (
            <StatusBadge active={true} label="EMERGENCY PRIORITY" color="#FF4D4D" icon={ShieldAlert} />
          )}
        </div>
      </header>

      {/* --- MAIN CORE --- */}
      <section className="main-view">
        <div className="glass-card map-viewport" style={{ padding: 0, overflow: 'hidden' }}>
            <MapContainer 
              center={mapCenter} 
              zoom={15} 
              style={{ height: '100%', width: '100%', filter: 'invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%)' }}
              zoomControl={false}
            >
              <TileLayer
                url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}"
                attribution='&copy; Google Maps'
              />
              <MapController center={mapCenter} />
              
              {state.intersections.map((int) => (
                <CircleMarker 
                  key={int.id}
                  center={mapCenter} 
                  pathOptions={{ 
                    color: int.signal.north_south === 'GREEN' ? '#00FF88' : '#FF4D4D',
                    fillColor: int.signal.north_south === 'GREEN' ? '#00FF88' : '#FF4D4D',
                    fillOpacity: 0.6,
                    weight: 2
                  }}
                  radius={12}
                >
                  <Popup>
                    <div style={{ color: '#000', fontFamily: 'Inter', fontSize: '12px' }}>
                      <strong style={{ display: 'block', marginBottom: '4px' }}>Intersection: {int.id}</strong>
                      <span style={{ color: int.signal.mode === 'EMERGENCY_OVERRIDE' ? '#FF4D4D' : '#00FF88', fontWeight: 700 }}>
                        Mode: {int.signal.mode}
                      </span>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>

            {/* Float Overlay */}
            <div style={{ position: 'absolute', top: '24px', left: '24px', zIndex: 1000 }}>
              <div className="status-badge" style={{ background: 'rgba(10,10,11,0.8)', backdropFilter: 'blur(10px)', color: '#6DDDFF', borderColor: 'rgba(109,221,255,0.2)' }}>
                <MapIcon size={14} color="#6DDDFF" /> CARTOGRAPHIC INTELLIGENCE ACTIVE
              </div>
            </div>
        </div>
      </section>

      {/* --- COMMAND PANELS --- */}
      <aside className="side-panel">
        
        {/* Signal Intelligence */}
        <div className="glass-card">
          <h2 style={{ fontSize: '12px', color: '#ADAAAB', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
            SIGNAL INTELLIGENCE <Activity size={16} color="#6DDDFF" />
          </h2>

          <div className="signal-group">
            <SignalIndicator state={intersection?.signal.north_south || 'RED'} label="NORTH-SOUTH" />
            <div style={{ width: '1px', height: '60px', backgroundColor: 'rgba(255,255,255,0.05)' }} />
            <SignalIndicator state={intersection?.signal.east_west || 'RED'} label="EAST-WEST" />
          </div>

          <div style={{ marginTop: '24px', padding: '20px', background: 'rgba(0,0,0,0.2)', borderRadius: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
             <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                <span style={{ color: '#ADAAAB' }}>ENGINE MODE</span>
                <span style={{ color: intersection?.signal.mode === 'EMERGENCY_OVERRIDE' ? '#FF4D4D' : '#00FF88', fontWeight: 800 }}>
                  {intersection?.signal.mode}
                </span>
             </div>
             <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                <span style={{ color: '#ADAAAB' }}>DECISION LATENCY</span>
                <span style={{ color: '#6DDDFF', fontWeight: 800 }}>8ms</span>
             </div>
          </div>
        </div>

        {/* Emergency Response */}
        <AnimatePresence>
          {state.emergency.active && (
            <motion.div 
              initial={{ opacity: 0, x: 50 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 50 }}
              className="glass-card" 
              style={{ background: 'rgba(255, 77, 77, 0.05)', borderColor: 'rgba(255, 77, 77, 0.2)' }}
            >
              <h2 style={{ fontSize: '12px', color: '#FF4D4D', marginBottom: '20px' }}>
                EMERGENCY PRIORITY OVERRIDE
              </h2>
              
              <div className="emergency-stats">
                <div>
                   <span className="eta-large">{state.emergency.estimated_arrival_sec}</span>
                   <span className="eta-unit">SEC</span>
                   <p style={{ fontSize: '9px', fontWeight: 800, color: '#ADAAAB', marginTop: '8px' }}>ESTIMATED ARRIVAL</p>
                </div>
                <div style={{ textAlign: 'right' }}>
                   <p style={{ color: '#FF4D4D', fontWeight: 800, fontSize: '16px' }}>LEVEL 1</p>
                   <p style={{ fontSize: '9px', fontWeight: 800, color: '#ADAAAB', marginTop: '4px' }}>PRIORITY STATUS</p>
                </div>
              </div>

              <div className="progress-bar-bg">
                 <motion.div 
                    initial={{ width: '0%' }}
                    animate={{ width: '85%' }}
                    className="progress-bar-fill" 
                 />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* System Trace */}
        <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: '8px', padding: '16px 8px' }}>
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#6DDDFF', animation: 'neon-pulse 2s infinite' }} />
          <span style={{ fontSize: '9px', fontWeight: 800, color: '#ADAAAB', letterSpacing: '0.1em' }}>STREAMING_SYNAPSE_CORE_PIPELINE_V2.0</span>
        </div>

      </aside>
    </div>
  );
}
