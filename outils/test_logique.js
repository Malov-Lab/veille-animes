/* Verifie la logique d'etat de la page : liste, masquage, retrait.
   Charge le vrai script de anime.html dans un DOM factice.            */
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("anime.html", "utf-8");
// Les declarations lexicales (const/let) d'un script ne deviennent pas des
// proprietes du contexte : on les expose via des accesseurs pour les tester.
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1] + `
;globalThis.__T = {
  get PROFILE(){return PROFILE}, get RATINGS(){return RATINGS},
  get TOP(){return TOP}, get HIDDEN(){return HIDDEN}, get REMOVED(){return REMOVED},
  get ADDED(){return ADDED},
  isInList, isExcluded, addToList, removeFromList, hideFromSuggestions,
  myList, topEntries,
};`;

// --- DOM minimal : le script cable des handlers au chargement.
const el = () => new Proxy({
  innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
  dataset: {}, style: {},
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  addEventListener() {}, closest: () => null, remove() {}, select() {},
  parentElement: null,
}, { get: (t, k) => (k in t ? t[k] : undefined), set: (t, k, v) => (t[k] = v, true) });

const store = new Map();
const ctx = {
  console,
  document: {
    getElementById: el,
    querySelector: el,
    querySelectorAll: () => [],
    addEventListener() {},
  },
  window: { scrollTo() {} },
  navigator: { clipboard: { writeText: async () => {} } },
  localStorage: {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, v),
    removeItem: k => store.delete(k),
  },
  fetch: async () => { throw new Error("reseau coupe pendant le test"); },
  setTimeout, clearTimeout, Date, Math, JSON, Number, String, Object, Array, Set, Map, Error,
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(code, ctx);
const T = ctx.__T;

// --- assertions
let ok = 0, ko = 0;
function check(label, cond) {
  if (cond) { ok++; console.log(`  ok    ${label}`); }
  else { ko++; console.log(`  ECHEC ${label}`); }
}

const crId = T.PROFILE.series[0].anilist_id;
const crTitle = T.PROFILE.series[0].title_english || T.PROFILE.series[0].title_romaji;
const NEW = { id: 999999001, title: "Serie de test", cover: "", genres: ["Action"] };

console.log("\n=== ETAT DE DEPART ===");
check("une serie Crunchyroll est dans la liste", T.isInList(crId));
check("elle est donc exclue des suggestions", T.isExcluded(crId));
check("une serie inconnue n'est pas dans la liste", !T.isInList(NEW.id));
check("et n'est pas exclue", !T.isExcluded(NEW.id));

console.log("\n=== « DEJA VU » SUR UNE SUGGESTION ===");
T.addToList(NEW);
check("elle entre dans la liste", T.isInList(NEW.id));
check("elle est exclue des suggestions", T.isExcluded(NEW.id));
check("elle est visible dans myList (donc notable)",
  T.myList().some(s => s.id === NEW.id));

console.log("\n=== NOTATION ET TOP ===");
T.RATINGS[NEW.id] = 5;
T.TOP.push(NEW.id);
check("la note est posee", T.RATINGS[NEW.id] === 5);
check("elle apparait dans le top", T.topEntries().some(s => s.id === NEW.id));

console.log("\n=== RETRAIT DE LA LISTE ===");
T.removeFromList(NEW.id);
check("elle sort de la liste", !T.isInList(NEW.id));
check("elle disparait de myList", !T.myList().some(s => s.id === NEW.id));
check("sa note est effacee", T.RATINGS[NEW.id] === undefined);
check("elle sort du top", !T.topEntries().some(s => s.id === NEW.id));
check("elle redevient proposable", !T.isExcluded(NEW.id));

console.log("\n=== RETRAIT D'UNE SERIE CRUNCHYROLL ===");
T.removeFromList(crId);
check("elle sort de la liste malgre l'historique", !T.isInList(crId));
check("elle disparait de myList", !T.myList().some(s => s.id === crId));

console.log("\n=== MASQUAGE (« pas envie ») ===");
const HIDE = 999999002;
T.hideFromSuggestions(HIDE);
check("elle est exclue des suggestions", T.isExcluded(HIDE));
check("mais elle n'entre PAS dans la liste", !T.isInList(HIDE));
check("et n'apparait pas dans myList", !T.myList().some(s => s.id === HIDE));

console.log("\n=== « DEJA VU » APRES UN MASQUAGE ===");
T.addToList({ id: HIDE, title: "Masquee puis vue", cover: "", genres: [] });
check("elle entre dans la liste", T.isInList(HIDE));
check("elle n'est plus seulement masquee", !T.HIDDEN.has(HIDE));

console.log("\n=== PERSISTANCE ===");
check("les retraits sont ecrits", store.has("anime_veille_removed"));
check("les ajouts sont ecrits", store.has("anime_veille_added"));
check("les masquages sont ecrits", store.has("anime_veille_seen"));

console.log(`\n=== ${ok} verifications passees, ${ko} echecs ===`);
process.exit(ko ? 1 : 0);
