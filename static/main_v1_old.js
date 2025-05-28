// 1. Verify we’re loading the right file
console.log("👋 main.js loaded");

// 2. Cesium setup
Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI0NTY4MWEyMC01NDg2LTRjYWEtODExOS0zMjQ3NGNiNDZkMmMiLCJpZCI6MjYwMTgwLCJpYXQiOjE3MzMzNjE1MDN9.OIim-jXbq3AfbnBU2rS2SGRG4DKwO88JR_2ycGIEk8w';

async function startViewer() {
  console.log("🛰 startViewer()");
  // 1. Terrain & viewer
  const terrain = await Cesium.CesiumTerrainProvider.fromIonAssetId(1);
  const viewer = new Cesium.Viewer('cesiumContainer', {
    terrainProvider: terrain,
    timeline: true,
    animation: true,
    shouldAnimate: true
  });
  // load and add the building 3D tileset
  const bkTileset = await Cesium.Cesium3DTileset.fromIonAssetId(2955578);
  viewer.scene.primitives.add(bkTileset);
  // once the tileset is ready, zoom to it _and then_ draw boxes
  await bkTileset.readyPromise;
  console.log("Tileset root.transform:", bkTileset.root.transform);
  // (this includes any RTC offset that Cesium applied under the hood)
  const modelMatrix = bkTileset.root.transform;
  // 1a. extract the tileset’s translation (ECEF meters):
  const m = modelMatrix.elements;
  const tilesetOrigin = new Cesium.Cartesian3(modelMatrix[12], modelMatrix[13],  modelMatrix[14]);
  console.log("tilesetOrigin (ECEF):", tilesetOrigin);
  // 1b) paste your JSON-logged center here:
  const sampleJsonCenter = new Cesium.Cartesian3(
    3923161.262283621,   // x from your console
    299837.8287741002,   // y
    5003152.480305793    // z
  );

  let count = 0;
  // ─── Addition: fetch and draw IFC space boxes ───
  try {
    const res = await fetch('/IFC_BB/spaces_bboxes.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const spaces = await res.json();
    spaces.forEach(space => {
      const [xmin, ymin, zmin, xmax, ymax, zmax] = space.bbox;

      // compute the local‐center and dims
      const localCenter = new Cesium.Cartesian3(
        (xmin + xmax) / 2,
        (ymin + ymax) / 2,
        (zmin + zmax) / 2
      );
      // Dimensions of the box
      const dims = new Cesium.Cartesian3(
        xmax - xmin,
        ymax - ymin,
        zmax - zmin
      );
      // transform to world coords
      let worldCenter = Cesium.Matrix4.multiplyByPoint(
        modelMatrix,
        localCenter,
        new Cesium.Cartesian3()
      );

      // apply north‐east shift
      const extraShift = new Cesium.Cartesian3(0.0, 0.0, 0.0); 
      Cesium.Cartesian3.add(worldCenter, extraShift, worldCenter);

      // 4) add exactly one entity
      viewer.entities.add({
        id: space.id,
        name: space.name,
        position: worldCenter,
        box: {
          dimensions: dims,
          material: Cesium.Color.YELLOW.withAlpha(0.2),
          outline: true,
          outlineColor: Cesium.Color.ORANGE
        },
      });

      console.log("Added shifted box for", space.name, "at", worldCenter);
    });
    
  } catch (e) {console.error('Failed to load or draw IFC bboxes:', e);}
  console.log("Total entities now in viewer:", viewer.entities.values.length);
  // ─────────────────────────────────────────────
  await viewer.zoomTo(bkTileset);

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