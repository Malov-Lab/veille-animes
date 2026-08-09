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
  set RATINGS(v){RATINGS = v}, set TOP(v){TOP = v},
  get ROOTS(){return ROOTS},
  // Le rattachement des saisons vient du reseau : en test, on l'injecte.
  setRoots(map){ ROOTS = map; refreshListRoots(); },
  isInList, isExcluded, addToList, removeFromList, hideFromSuggestions,
  myList, topEntries, rootOf, groupByWork, mergeState, countMerged,
  tasteProfile, genreFit, lateInterest, memberIds, refreshListRoots,
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

/* ================= regroupement par oeuvre =================
   Scenario : une serie de l'historique Crunchyroll (la saison 1) et une saison 2
   ajoutee a la main. AniList les compte separement, la page doit n'en faire
   qu'une seule ligne, portant la meilleure des deux notes.                  */
console.log("\n=== SAISONS D'UNE MEME OEUVRE ===");
// On repart d'un etat propre : les tests precedents ont retire des series.
store.clear();
T.setRoots({});
T.RATINGS = {};
T.TOP = [];
T.refreshListRoots();

const S1 = T.PROFILE.series[1].anilist_id;      // saison 1, vue sur Crunchyroll
const S2 = 999999201;                            // saison 2, ajoutee a la main
const AUTRE = T.PROFILE.series[2].anilist_id;    // oeuvre sans rapport

T.addToList({ id: S2, title: "Oeuvre test Season 2", cover: "", genres: ["Action"] });
check("sans rattachement, les deux saisons font deux lignes",
  T.myList().filter(s => s.id === S1 || s.id === S2).length === 2);

T.setRoots({ [S2]: { root: S1, title: "Oeuvre test", cover: "" } });
check("la saison 2 pointe vers la saison 1", T.rootOf(S2) === S1);
check("une serie sans rattachement connu reste sa propre racine", T.rootOf(AUTRE) === AUTRE);

const groupe = T.myList().find(s => s.id === S1);
check("les deux saisons ne font plus qu'une ligne", !!groupe && groupe.parts.length === 2);
check("la saison 2 n'a plus de ligne a elle", !T.myList().some(s => s.id === S2));
check("la saison 2 compte comme deja dans la liste", T.isInList(S2));
check("elle est donc exclue des suggestions", T.isExcluded(S2));

console.log("\n=== FUSION DES NOTES : LA MEILLEURE GAGNE ===");
T.RATINGS = { [S1]: 3, [S2]: 5, [AUTRE]: 4 };
T.TOP = [S2, AUTRE, S1];
T.mergeState();
check("l'oeuvre garde la meilleure des deux notes", T.RATINGS[S1] === 5);
check("la note de la saison 2 est absorbee", T.RATINGS[S2] === undefined);
check("une oeuvre sans double n'est pas touchee", T.RATINGS[AUTRE] === 4);
check("le top ne contient plus qu'une entree pour l'oeuvre",
  T.TOP.filter(x => x === S1).length === 1 && !T.TOP.includes(S2));
check("le rang de la mieux placee est conserve", T.TOP[0] === S1);
check("le top garde l'autre oeuvre", T.TOP.includes(AUTRE));
check("l'ajout manuel absorbe sort de ADDED", !T.ADDED.some(a => a.id === S2));

console.log("\n=== LA FUSION EST IDEMPOTENTE ===");
const avant = JSON.stringify([T.RATINGS, T.TOP, T.ADDED]);
T.mergeState();
check("repasser dessus ne change rien", JSON.stringify([T.RATINGS, T.TOP, T.ADDED]) === avant);

console.log("\n=== RETRAIT D'UNE OEUVRE REGROUPEE ===");
T.removeFromList(S2);          // le geste porte sur la saison 2
check("l'oeuvre entiere sort de la liste", !T.isInList(S1) && !T.isInList(S2));
check("sa note part avec elle", T.RATINGS[S1] === undefined);
check("elle sort du top", !T.TOP.includes(S1));

/* ================= tri par interet ================= */
console.log("\n=== AFFINITE DE GENRES ===");
const taste = { Action: 1, Comedy: 0.9, Drama: 0.1, Ecchi: -0.8, Horror: -0.9 };
check("une serie qui colle bat une serie qui ne colle pas",
  T.genreFit(["Action", "Comedy"], taste) > T.genreFit(["Horror", "Ecchi"], taste));
check("empiler les genres tiedes ne bat pas deux genres forts",
  T.genreFit(["Action", "Comedy"], taste) >
  T.genreFit(["Drama", "Drama", "Drama", "Drama", "Drama", "Drama"], taste));
check("sans genre, affinite nulle", T.genreFit([], taste) === 0);
check("un genre rejete tire vers le bas", T.genreFit(["Horror"], taste) < 0);

console.log("\n=== ORDRE DU RETARD ===");
const hier = new Date(Date.now() - 2 * 86400000).toISOString();
const vieux = new Date(Date.now() - 700 * 86400000).toISOString();
const coupDeCoeur = T.lateInterest(
  { genres: ["Action"], rating: 5, lastWatched: hier, behind: 2 }, taste);
const grosRetard = T.lateInterest(
  { genres: ["Horror"], rating: 0, lastWatched: vieux, behind: 40 }, taste);
check("un coup de coeur repris hier passe devant un gros retard oublie",
  coupDeCoeur > grosRetard);
check("a tout le reste egal, une serie mal notee passe derriere une non notee",
  T.lateInterest({ genres: ["Action"], rating: 2, lastWatched: hier, behind: 5 }, taste) <
  T.lateInterest({ genres: ["Action"], rating: 0, lastWatched: hier, behind: 5 }, taste));
check("a note et genres egaux, le petit retard passe devant",
  T.lateInterest({ genres: ["Action"], rating: 4, lastWatched: hier, behind: 2 }, taste) >
  T.lateInterest({ genres: ["Action"], rating: 4, lastWatched: hier, behind: 30 }, taste));
check("a retard egal, la serie reprise recemment passe devant",
  T.lateInterest({ genres: ["Action"], rating: 4, lastWatched: hier, behind: 5 }, taste) >
  T.lateInterest({ genres: ["Action"], rating: 4, lastWatched: vieux, behind: 5 }, taste));

console.log(`\n=== ${ok} verifications passees, ${ko} echecs ===`);
process.exit(ko ? 1 : 0);
