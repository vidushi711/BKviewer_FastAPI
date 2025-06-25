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
  // 1c) fudge = tilesetOrigin − sampleJsonCenter
  const fudge = Cesium.Cartesian3.subtract(
    tilesetOrigin,
    sampleJsonCenter,
    new Cesium.Cartesian3()
  );
  console.log("Computed fudge (m):", fudge);

  let count = 0;
  // ─── Addition: fetch and draw IFC space boxes ───
  try {
    const res = await fetch('/IFC_BB/spaces_bboxes.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const spaces = await res.json();
    spaces.forEach(space => {
      const [xmin, ymin, zmin, xmax, ymax, zmax] = space.bbox;

      // center & dimensions in the same CRS as the tileset
      const localCenter = new Cesium.Cartesian3(
        (xmin + xmax) / 2,
        (ymin + ymax) / 2,
        (zmin + zmax) / 2
      );
      // Transform into world coords
      const worldCenter = Cesium.Matrix4.multiplyByPoint(
        modelMatrix,
        localCenter,
        new Cesium.Cartesian3()
      );
      // Dimensions of the box
      const dims = new Cesium.Cartesian3(
        xmax - xmin,
        ymax - ymin,
        zmax - zmin
      );
      // Add the box entity
      const ent = viewer.entities.add({
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
      console.log("Added box for", space.name, "at", worldCenter);
      count += 1;      
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
    const { predicted_temp, solar_inflow, room_volume, windows } = await resp.json();
    // D) Show predicted temperature
    predictedEl.textContent = predicted_temp.toFixed(1);
    console.log('Predicted temp from server:', predicted_temp);
    // E) Show other room data
    document.getElementById('solarInflow').textContent  = solar_inflow.toFixed(1);
    document.getElementById('roomVolume').textContent   = room_volume.toFixed(0);
    // F) Render windows list
    const ul = document.getElementById('windowsUl');
    ul.innerHTML = '';
    windows.forEach(w => {
      const li = document.createElement('li');
      // translate azimuth degrees into N, NE, E, etc.
      const compass = azimuthToCompass(w.azimuth);
      li.textContent = 
        `Area: ${w.area.toFixed(1)} m², SHGC: ${w.shgc.toFixed(2)}, ` +
        `Tilt: ${w.tilt.toFixed(1)}°, Facing: ${compass}, Azimuth: ${w.azimuth.toFixed(1)}°`;
      ul.appendChild(li);
    });

  } catch (err) {
    console.error('Error fetching prediction:', err);
    predictedEl.textContent = 'Error';
  } finally {
    spinner.style.display = 'none';
  }
});

function azimuthToCompass(az) {
  if      (az >= 337.5 || az <  22.5) return 'N';
  else if (az <   67.5)               return 'NE';
  else if (az <  112.5)               return 'E';
  else if (az <  157.5)               return 'SE';
  else if (az <  202.5)               return 'S';
  else if (az <  247.5)               return 'SW';
  else if (az <  292.5)               return 'W';
  else                                return 'NW';
}
document.addEventListener("DOMContentLoaded", () => {
    const container = document.getElementById("temperature-display");
    const rooms = [
        {
            name: "BG.West.010",
            url: "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(1)/Observations?$orderby=phenomenonTime desc&$top=1"
        },
        {
            name: "BG.West.270",
            url: "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(7)/Observations?$orderby=phenomenonTime desc&$top=1"
        },
        {
            name: "01.West.120",
            url: "https://multicare.bk.tudelft.nl/FROST-Server/v1.0/Datastreams(13)/Observations?$orderby=phenomenonTime desc&$top=1"
        }
    ];

    rooms.forEach(room => {
        fetch(room.url)
            .then(res => res.json())
            .then(data => {
                if (data.value && data.value.length > 0 && 'result' in data.value[0]) {
                  const obs = data.value[0];
                  const temp = obs.result;
                  const time = new Date(obs.phenomenonTime);
                  const timeString = time.toLocaleString([], {
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit'
                  });

                  const div = document.createElement("div");
                  div.className = "room-temp";
                  div.innerText = `${room.name}: ${temp.toFixed(1)}°C (at ${timeString})`;
                  container.appendChild(div);
              } else {
                  const div = document.createElement("div");
                  div.className = "room-temp";
                  div.innerText = `${room.name}: data unavailable`;
                  container.appendChild(div);
              }
            })
            .catch(err => {
                console.error(`Error loading data for ${room.name}:`, err);
            });
    });
});