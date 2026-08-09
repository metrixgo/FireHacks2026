import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MapContainer, TileLayer, Polyline, Marker, Popup } from 'react-leaflet';
import { MapPin, Navigation, Wind, Shield, Leaf, Star, Loader2 } from 'lucide-react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './App.css';

// Fix for default marker icons in Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

function App() {
  const [coordinates, setCoordinates] = useState({ latitude: 40.7128, longitude: -74.0060 }); // Default: NYC
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState(null);
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [error, setError] = useState('');
  const [apiUrl, setApiUrl] = useState(import.meta.env.VITE_API_URL || 'http://localhost:8000');

  // Get user's current location
  const getCurrentLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setCoordinates({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude
          });
        },
        (error) => {
          console.error('Error getting location:', error);
          setError('Could not get your location. Using default coordinates.');
        }
      );
    } else {
      setError('Geolocation is not supported by your browser.');
    }
  };

  useEffect(() => {
    getCurrentLocation();
  }, []);

  const handleFindRoute = async () => {
    if (!prompt.trim()) {
      setError('Please enter a prompt');
      return;
    }

    setLoading(true);
    setError('');
    setResponse(null);

    try {
      const result = await axios.post(`${apiUrl}/api/plan-route`, {
        latitude: coordinates.latitude,
        longitude: coordinates.longitude,
        prompt: prompt
      });
      setResponse(result.data);
      setSelectedRouteId(result.data.selected_route.id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to plan route. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleRouteSelect = (routeId) => {
    setSelectedRouteId(routeId);
  };

  const getSelectedRoute = () => {
    if (!response) return null;
    return response.candidate_routes.find(r => r.id === selectedRouteId) || response.selected_route;
  };

  const renderRoutePolyline = () => {
    const selectedRoute = getSelectedRoute();
    if (!selectedRoute || !selectedRoute.geojson) return null;

    try {
      const coordinates = selectedRoute.geojson.geometry.coordinates.map(coord => [coord[1], coord[0]]);
      return (
        <Polyline
          positions={coordinates}
          color="#3b82f6"
          weight={5}
          opacity={0.8}
        />
      );
    } catch (e) {
      console.error('Error rendering route:', e);
      return null;
    }
  };

  return (
    <div className="app">
      {/* Left Panel - AI & Route Control */}
      <div className="left-panel">
        <div className="panel-header">
          <h1>🏃 AI Route Planner</h1>
          <p>Find the perfect exercise route based on air quality, safety, and scenery</p>
        </div>

        <div className="coordinates-section">
          <div className="coordinate-input">
            <label>
              <MapPin size={16} />
              Latitude
            </label>
            <input
              type="number"
              step="any"
              value={coordinates.latitude}
              onChange={(e) => setCoordinates({ ...coordinates, latitude: parseFloat(e.target.value) })}
            />
          </div>
          <div className="coordinate-input">
            <label>
              <MapPin size={16} />
              Longitude
            </label>
            <input
              type="number"
              step="any"
              value={coordinates.longitude}
              onChange={(e) => setCoordinates({ ...coordinates, longitude: parseFloat(e.target.value) })}
            />
          </div>
          <button onClick={getCurrentLocation} className="location-btn">
            <Navigation size={16} />
            Use My Location
          </button>
        </div>

        <div className="prompt-section">
          <label>Where would you like to exercise?</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g., 'I want to run for 5 miles' or 'I need a 3km walking route'"
            rows={3}
          />
        </div>

        <button
          onClick={handleFindRoute}
          disabled={loading}
          className="find-route-btn"
        >
          {loading ? (
            <>
              <Loader2 size={20} className="spin" />
              Finding Best Route...
            </>
          ) : (
            <>
              <Star size={20} />
              Find Best Route
            </>
          )}
        </button>

        {error && <div className="error-message">{error}</div>}

        {response && (
          <div className="results-section">
            <div className="ai-summary">
              <h3>🤖 AI Summary</h3>
              <p>{response.ai_summary}</p>
            </div>

            <div className="route-stats">
              <div className="stat">
                <Wind size={18} />
                <span>AQI: {response.local_aqi}</span>
              </div>
              <div className="stat">
                <Navigation size={18} />
                <span>Target: {response.target_miles.toFixed(2)} mi</span>
              </div>
              <div className="stat">
                <Star size={18} />
                <span>Activity: {response.activity}</span>
              </div>
            </div>

            <div className="candidate-routes">
              <h3>🗺️ Candidate Routes</h3>
              <div className="routes-list">
                {response.candidate_routes.map((route, index) => (
                  <div
                    key={route.id}
                    className={`route-card ${selectedRouteId === route.id ? 'selected' : ''}`}
                    onClick={() => handleRouteSelect(route.id)}
                  >
                    <div className="route-header">
                      <span className="route-number">#{index + 1}</span>
                      <span className="route-score">
                        Score: {route.overall_score.toFixed(1)}/100
                      </span>
                    </div>
                    <div className="route-details">
                      <div className="detail">
                        <Navigation size={14} />
                        <span>{route.distance_miles.toFixed(2)} mi</span>
                      </div>
                      <div className="detail">
                        <Wind size={14} />
                        <span>AQI: {route.aqi}</span>
                      </div>
                    </div>
                    <div className="route-breakdown">
                      <div className="breakdown-item">
                        <span>Distance</span>
                        <div className="progress-bar">
                          <div className="progress" style={{ width: `${route.score_dist}%` }} />
                        </div>
                        <span>{route.score_dist.toFixed(0)}</span>
                      </div>
                      <div className="breakdown-item">
                        <span>Air Quality</span>
                        <div className="progress-bar">
                          <div className="progress" style={{ width: `${route.score_aqi}%` }} />
                        </div>
                        <span>{route.score_aqi.toFixed(0)}</span>
                      </div>
                      <div className="breakdown-item">
                        <span>Greenery</span>
                        <div className="progress-bar">
                          <div className="progress" style={{ width: `${route.score_green}%` }} />
                        </div>
                        <span>{route.score_green.toFixed(0)}</span>
                      </div>
                      <div className="breakdown-item">
                        <span>Safety</span>
                        <div className="progress-bar">
                          <div className="progress" style={{ width: `${route.score_safe}%` }} />
                        </div>
                        <span>{route.score_safe.toFixed(0)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right Panel - Map View */}
      <div className="right-panel">
        <MapContainer
          center={[coordinates.latitude, coordinates.longitude]}
          zoom={13}
          style={{ height: '100%', width: '100%' }}
          key={`${coordinates.latitude}-${coordinates.longitude}`}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Marker position={[coordinates.latitude, coordinates.longitude]}>
            <Popup>Your Location</Popup>
          </Marker>
          {renderRoutePolyline()}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;
