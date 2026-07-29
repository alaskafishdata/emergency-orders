import * as fs from "fs/promises";
import * as path from "path";

const OUTPUT_DIR = path.join(process.cwd(), "data");

// ADF&G EONR region codes for sport fishing orders
const SPORT_REGIONS = [
  { code: "NR", name: "Northcentral" },   // Kenai, Mat-Su, Copper River
  { code: "SR", name: "Southcentral" },
  { code: "SE", name: "Southeast" },
  { code: "WR", name: "Western" },        // Bristol Bay, Chignik
  { code: "AR", name: "Arctic" },         // Norton Sound, Kotzebue
];

const YEAR = new Date().getFullYear();

interface EO {
  id: string;
  title: string;
  region: string;
  date: string;
  effectiveStart: string;
  effectiveEnd: string;
  severity: string;
  regulatoryAction: string;
  species: string[];
  sourceUrl: string;
}

async function scrapeRegion(regionCode: string, regionName: string): Promise<EO[]> {
  const url = `https://www.adfg.alaska.gov/sf/EONR/index.cfm?ADFG=region.${regionCode}&Year=${YEAR}`;
  console.log(`  Fetching ${regionName} (${regionCode})...`);

  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "AlaskaFishData-PublicDataBot/1.0 (github.com/alaskafishdata/emergency-orders)" }
    });
    if (!res.ok) {
      console.warn(`  [WARN] ${regionName}: HTTP ${res.status}`);
      return [];
    }

    const html = await res.text();
    const orders: EO[] = [];

    // Parse EO table rows from ADF&G EONR HTML
    const rowRegex = /<tr[^>]*class="[^"]*eo-row[^"]*"[^>]*>([\s\S]*?)<\/tr>/gi;
    const cellRegex = /<td[^>]*>([\s\S]*?)<\/td>/gi;
    const linkRegex = /href="([^"]+)"[^>]*>([^<]+)</;
    const idRegex = /(\d+-[A-Z]+-\d+-\d+-\d+)/;

    let rowMatch;
    while ((rowMatch = rowRegex.exec(html)) !== null) {
      const rowHtml = rowMatch[1];
      const cells: string[] = [];
      let cellMatch;
      while ((cellMatch = cellRegex.exec(rowHtml)) !== null) {
        cells.push(cellMatch[1].replace(/<[^>]*>/g, "").trim());
      }

      if (cells.length >= 3) {
        const idMatch = (cells[0] || "").match(idRegex);
        const eoId = idMatch ? idMatch[1] : `EO-${regionCode}-${Date.now()}`;
        
        orders.push({
          id: eoId,
          title: cells[1] || "Emergency Order",
          region: regionName,
          date: cells[2] || new Date().toISOString().split("T")[0],
          effectiveStart: cells[3] || cells[2] || "",
          effectiveEnd: cells[4] || "",
          severity: determineSeverity(cells[1] || ""),
          regulatoryAction: determineAction(cells[1] || ""),
          species: extractSpecies(cells[1] || ""),
          sourceUrl: url,
        });
      }
    }

    return orders;
  } catch (e) {
    console.error(`  [ERR] ${regionName}:`, e);
    return [];
  }
}

function determineSeverity(title: string): string {
  const t = title.toLowerCase();
  if (t.includes("clos")) return "critical";
  if (t.includes("restrict") || t.includes("reduc") || t.includes("limit")) return "warning";
  if (t.includes("open") || t.includes("extend") || t.includes("increas")) return "liberalize";
  return "info";
}

function determineAction(title: string): string {
  const t = title.toLowerCase();
  if (t.includes("clos")) return "close";
  if (t.includes("restrict") || t.includes("reduc")) return "restrict";
  if (t.includes("open")) return "open";
  if (t.includes("extend") || t.includes("increas")) return "liberalize";
  return "modify";
}

function extractSpecies(title: string): string[] {
  const species: string[] = [];
  const t = title.toLowerCase();
  if (t.includes("king") || t.includes("chinook")) species.push("Chinook");
  if (t.includes("sockeye") || t.includes("red")) species.push("Sockeye");
  if (t.includes("coho") || t.includes("silver")) species.push("Coho");
  if (t.includes("chum") || t.includes("dog")) species.push("Chum");
  if (t.includes("pink") || t.includes("humpy")) species.push("Pink");
  if (t.includes("halibut")) species.push("Halibut");
  if (t.includes("steelhead")) species.push("Steelhead");
  if (species.length === 0) species.push("Salmon");
  return species;
}

async function main() {
  console.log("AlaskaFishData | Emergency Orders Scraper");
  console.log("Source: ADF&G Emergency Order Notification & Reporting (EONR) System");
  console.log(`Year: ${YEAR}\n`);

  await fs.mkdir(OUTPUT_DIR, { recursive: true });

  const allSportEOs: EO[] = [];

  for (const region of SPORT_REGIONS) {
    const eos = await scrapeRegion(region.code, region.name);
    allSportEOs.push(...eos);
    console.log(`  → ${eos.length} orders found in ${region.name}`);
    await new Promise(r => setTimeout(r, 800)); // polite delay
  }

  const output = {
    _meta: {
      source: "ADF&G EONR System — https://www.adfg.alaska.gov/sf/EONR/",
      generated: new Date().toISOString(),
      year: YEAR,
      count: allSportEOs.length,
    },
    sport: allSportEOs.sort((a, b) => b.date.localeCompare(a.date)),
    commercial: [],
  };

  await fs.writeFile(
    path.join(OUTPUT_DIR, "live-eo.json"),
    JSON.stringify(output, null, 2)
  );

  console.log(`\n✓ Wrote ${allSportEOs.length} EOs → data/live-eo.json`);
}

main().catch(console.error);
