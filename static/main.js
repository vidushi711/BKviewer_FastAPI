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
const globalIdEl  = document.getElementById('globalIdDisplay');

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
    // C) Fetch room details
    const resp = await fetch(`/api/rooms/${encodeURIComponent(roomName)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const { global_id } = await resp.json();
    // D) Show Global ID
    globalIdEl.textContent = global_id;
    console.log('GlobalId from server:', global_id);
  } catch (err) {
    globalIdEl.textContent = 'Error';
    console.error('Error fetching room info:', err);
  } finally {
    // E) always hide the spinner at the end
    spinner.style.display = 'none';
  }
});