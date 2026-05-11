/**
 * PhraseListEditor — structured editor for alert phrases and wake words.
 *
 * Two modes:
 *   - "alert": each row has { text, severity (1..5), regex (bool) }.
 *   - "wake": each row has { text }.
 */
import React from "react";
import { View, Text, TextInput, Pressable, Switch, StyleSheet } from "react-native";

export default function PhraseListEditor({ value = [], onChange, mode = "alert", addLabel }) {
  const add = () => {
    const item =
      mode === "alert" ? { text: "", severity: 3, regex: false } : { text: "" };
    onChange([...(value || []), item]);
  };

  const update = (idx, patch) => {
    const next = (value || []).map((it, i) => (i === idx ? { ...it, ...patch } : it));
    onChange(next);
  };

  const remove = (idx) => {
    onChange((value || []).filter((_, i) => i !== idx));
  };

  return (
    <View style={styles.container}>
      {(value || []).map((item, idx) => (
        <View key={idx} style={styles.row}>
          <TextInput
            style={styles.input}
            value={item.text}
            onChangeText={(t) => update(idx, { text: t })}
            placeholder={mode === "alert" ? "Frase o expresión regular" : "Palabra de activación"}
            autoCapitalize="none"
          />

          {mode === "alert" ? (
            <View style={styles.controls}>
              <View style={styles.sevRow}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <Pressable
                    key={n}
                    style={[styles.sevBtn, item.severity === n && styles.sevBtnActive]}
                    onPress={() => update(idx, { severity: n })}
                  >
                    <Text style={[styles.sevText, item.severity === n && styles.sevTextActive]}>
                      {n}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <View style={styles.regexRow}>
                <Text style={styles.regexLabel}>regex</Text>
                <Switch
                  value={!!item.regex}
                  onValueChange={(v) => update(idx, { regex: v })}
                />
              </View>
            </View>
          ) : null}

          <Pressable style={styles.deleteBtn} onPress={() => remove(idx)}>
            <Text style={styles.deleteText}>✕</Text>
          </Pressable>
        </View>
      ))}

      <Pressable style={styles.addBtn} onPress={add}>
        <Text style={styles.addText}>+ {addLabel || (mode === "alert" ? "Añadir frase" : "Añadir palabra")}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginBottom: 8 },
  row: {
    backgroundColor: "#fff",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#E0E0E0",
    padding: 10,
    marginBottom: 8,
  },
  input: {
    backgroundColor: "#FAFAFA",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#E0E0E0",
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 14,
    marginBottom: 8,
  },
  controls: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sevRow: { flexDirection: "row", gap: 4 },
  sevBtn: {
    width: 28,
    height: 28,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#CCC",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#fff",
  },
  sevBtnActive: { backgroundColor: "#E74C3C", borderColor: "#E74C3C" },
  sevText: { fontSize: 13, color: "#555" },
  sevTextActive: { color: "#fff", fontWeight: "700" },
  regexRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  regexLabel: { fontSize: 13, color: "#555" },
  deleteBtn: {
    position: "absolute",
    top: 8,
    right: 8,
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FDECEC",
  },
  deleteText: { color: "#E74C3C", fontWeight: "700", fontSize: 14 },
  addBtn: {
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: "#4A90D9",
    alignItems: "center",
  },
  addText: { color: "#4A90D9", fontWeight: "600" },
});
