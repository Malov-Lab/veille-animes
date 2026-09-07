/* Verifie le cache de rattachement : invalidation par version, et refus de
   figer une requete perdue. Le reseau est simule.                        */
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync("anime.html", "utf-8");
const body = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const el = () => new Proxy({ innerHTML:"", textContent:"", value:"", hidden:false, disabled:false,
  dataset:{}, style:{}, classList:{add(){},remove(){},toggle(){},contains:()=>false},
  addEventListener(){}, closest:()=>null, remove(){}, select(){}, parentElement:null },
  { get:(t,k)=>(k in t?t[k]:undefined), set:(t,k,v)=>(t[k]=v,true) });

function monter(cacheInitial, reponses) {
  const store = new Map();
  if (cacheInitial !== undefined) store.set("anime_veille_roots", JSON.stringify(cacheInitial));
  let appels = 0;
  const ctx = {
    console, document:{getElementById:el, querySelector:el, querySelectorAll:()=>[], addEventListener(){}},
    window:{scrollTo(){}}, navigator:{clipboard:{writeText:async()=>{}}},
    localStorage:{ getItem:k=>(store.has(k)?store.get(k):null), setItem:(k,v)=>store.set(k,v), removeItem:k=>store.delete(k) },
    fetch: async (url, opts) => {
      appels++;
      const q = JSON.parse(opts.body).query;
      const ids = [...q.matchAll(/Media\(id:\s*(\d+)\)/g)].map(m => Number(m[1]));
      const data = {};
      ids.forEach((id, i) => { data["r" + i] = reponses[id] ?? null; });
      return { ok:true, status:200, json: async () => ({ data }) };
    },
    setTimeout, clearTimeout, Date, Math, JSON, Number, String, Object, Array, Set, Map, Error, Promise,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(body + `
;globalThis.__R = { get ROOTS(){return ROOTS}, resolveRoots,
   lire: () => JSON.parse(localStorage.getItem("anime_veille_roots")) };`, ctx);
  return { R: ctx.__R, nbAppels: () => appels };
}

const serie = (id, titre, prequel) => ({ id, title:{english:titre,romaji:titre}, format:"TV",
  coverImage:{large:""}, relations:{edges: prequel ? [{relationType:"PREQUEL", node:{id:prequel, type:"ANIME", format:"TV"}}] : []} });

let ok=0, ko=0;
const check = (l,c) => c ? (ok++, console.log("  ok    "+l)) : (ko++, console.log("  ECHEC "+l));

console.log("\n=== UN CACHE DE L'ANCIEN FORMAT EST JETE ===");
{ const {R} = monter({ 20958: { root: 20958, title: "AoT S2" } }, {});
  check("l'ancien cache nu n'est pas relu", Object.keys(R.ROOTS).length === 0); }

console.log("\n=== UN CACHE A LA BONNE VERSION EST RELU ===");
{ const {R} = monter({ v:2, map:{ 20958: { root:16498, title:"Attack on Titan" } } }, {});
  check("la racine mise en cache est reprise", R.ROOTS[20958]?.root === 16498); }

console.log("\n=== UNE CHAINE COMPLETE EST RESOLUE ET ECRITE ===");
(async () => {
  { const {R} = monter(undefined, { 99147: serie(99147,"AoT S3",20958), 20958: serie(20958,"AoT S2",16498), 16498: serie(16498,"Attack on Titan") });
    const n = await R.resolveRoots([99147]);
    check("la saison 3 remonte a la saison 1", R.ROOTS[99147]?.root === 16498);
    check("les maillons intermediaires sont caches aussi", R.ROOTS[20958]?.root === 16498);
    check("le compteur annonce ce qui a ete resolu", n === 3);
    check("le cache ecrit porte le numero de version", R.lire()?.v === 2); }

  console.log("\n=== UNE REQUETE PERDUE N'EST PAS FIGEE EN CACHE ===");
  { const {R} = monter(undefined, { 99147: serie(99147,"AoT S3",20958) });  // 20958 absent
    await R.resolveRoots([99147]);
    check("la serie au maillon manquant n'est pas ecrite", !(99147 in R.ROOTS));
    check("le maillon manquant lui-meme n'est pas ecrit", !(20958 in R.ROOTS)); }

  console.log("\n=== ET ELLE EST RETENTEE A L'OUVERTURE SUIVANTE ===");
  { const {R} = monter(undefined, { 99147: serie(99147,"AoT S3",20958) });
    await R.resolveRoots([99147]);
    const avant = R.nbAppels; // reseau retabli au second passage
    const {R: R2} = monter(R.lire() ?? undefined, { 99147: serie(99147,"AoT S3",20958), 20958: serie(20958,"AoT S2",16498), 16498: serie(16498,"Attack on Titan") });
    await R2.resolveRoots([99147]);
    check("la seconde tentative aboutit", R2.ROOTS[99147]?.root === 16498); }

  console.log("\n=== UNE SERIE SANS PREQUEL EST BIEN UN VERDICT ===");
  { const {R} = monter(undefined, { 16498: serie(16498,"Attack on Titan") });
    await R.resolveRoots([16498]);
    check("elle est sa propre racine, et c'est ecrit", R.ROOTS[16498]?.root === 16498); }

  console.log(`\n=== ${ok} verifications passees, ${ko} echecs ===`);
  process.exit(ko ? 1 : 0);
})();
