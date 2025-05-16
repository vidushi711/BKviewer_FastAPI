// 1. Verify we’re loading the right file
console.log("👋 main.js loaded");

// 2. Cesium setup
Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI0NTY4MWEyMC01NDg2LTRjYWEtODExOS0zMjQ3NGNiNDZkMmMiLCJpZCI6MjYwMTgwLCJpYXQiOjE3MzMzNjE1MDN9.OIim-jXbq3AfbnBU2rS2SGRG4DKwO88JR_2ycGIEk8w';

async function startViewer() {
  const terrain = await Cesium.CesiumTerrainProvider.fromIonAssetId(1);
  const viewer = new Cesium.Viewer('cesiumContainer', {
    terrainProvider: terrain,
    timeline: true,
    animation: true,
    shouldAnimate: true
  });
  const bkTileset = await Cesium.Cesium3DTileset.fromIonAssetId(2955578);
  viewer.scene.primitives.add(bkTileset);
  viewer.zoomTo(bkTileset);
}

// 3. Load rooms into the dropdown
async function loadRooms() {
  const response = await fetch('./bk_rooms.csv');
  const text     = await response.text();
  const rows     = text.split('\n').slice(1); // skip header
  const select   = document.getElementById('roomSelect');

  for (let row of rows) {
    if (!row.trim()) continue;
    const [shortName, longName, globalId] = row.split(',');
    const option = document.createElement('option');
    option.value       = longName.trim();     // what we send to the API
    option.dataset.gid = globalId.trim();     // for local lookup if desired
    option.textContent = `${shortName.trim()} - ${longName.trim()}`;
    select.appendChild(option);
  }
}

// 4. Wire it all up once the script loads
startViewer();
loadRooms();

const selectEl    = document.getElementById('roomSelect');
const displayEl   = document.getElementById('selectedRoom');
// grab the <span> where we'll show the predicted temperature
const predictedEl = document.getElementById('predictedTemp');

// 5. Handle user selection
selectEl.addEventListener('change', async (evt) => {
  console.log('🔔 change event fired!', evt.target.value);
  const roomName = evt.target.value;
  if (!roomName) { return; }

  // A) Update “You picked” display
  displayEl.textContent = roomName;
  // grab spinner ONCE
  const spinner = document.getElementById('loadingSpinner');
  // B) now that we know there's a valid room, show it
  spinner.style.display = 'flex';

  try {
    // C) calling FastAPI
    const resp = await fetch(`/api/simulate/${encodeURIComponent(roomName)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const { predicted_temp } = await resp.json();
    // D) Show predicted temperature
    predictedEl.textContent = predicted_temp.toFixed(1);
    console.log('Predicted temp from server:', predicted_temp);
  } catch (err) {
    console.error('Error fetching prediction:', err);
    predictedEl.textContent = 'Error';
  } finally {
    // E) always hide the spinner at the end
    spinner.style.display = 'none';
  }
});