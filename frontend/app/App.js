/**
 * TFG-DEMENCIA - Navigation root.
 *
 * React Navigation native stack. On boot we try to restore the session from
 * SecureStore; if a token is present the app skips straight to the role's
 * home screen. The Android hardware back button now pops screens instead
 * of exiting the app.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { StatusBar } from "expo-status-bar";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { getCurrentUser, setToken } from "./src/services/api";
import { loadSession, saveSession, clearSession } from "./src/services/session";

import LoginScreen from "./src/screens/LoginScreen";
import PatientHomeScreen from "./src/screens/PatientHomeScreen";
import CaregiverHomeScreen from "./src/screens/CaregiverHomeScreen";
import PatientContextScreen from "./src/screens/PatientContextScreen";
import SettingsScreen from "./src/screens/SettingsScreen";

const Stack = createNativeStackNavigator();

export default function App() {
  const [booted, setBooted] = useState(false);
  const [initialUser, setInitialUser] = useState(null);

  useEffect(() => {
    (async () => {
      const s = await loadSession();
      if (s) {
        let user = s.user;
        try {
          const currentUser = await getCurrentUser();
          user = {
            ...user,
            ...currentUser,
            user_id: currentUser.id || user.user_id,
          };
          await saveSession(s.token, user);
        } catch (e) {
          console.warn("Could not refresh stored session user:", e?.message || e);
        }
        setInitialUser(user);
      }
      setBooted(true);
    })();
  }, []);

  const makeLogout = useCallback((navigation) => async () => {
    await clearSession();
    setInitialUser(null);
    navigation.reset({ index: 0, routes: [{ name: "Login" }] });
  }, []);

  if (!booted) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const initialRouteName = initialUser
    ? initialUser.role === "caregiver"
      ? "CaregiverHome"
      : "PatientHome"
    : "Login";

  return (
    <>
      <StatusBar style="dark" />
      <NavigationContainer>
        <Stack.Navigator
          initialRouteName={initialRouteName}
          screenOptions={{ headerShown: false }}
        >
          <Stack.Screen name="Login">
            {(props) => (
              <LoginScreen
                {...props}
                onLogin={(data) => {
                  setToken(data.access_token);
                  setInitialUser(data);
                  props.navigation.reset({
                    index: 0,
                    routes: [
                      {
                        name:
                          data.role === "caregiver" ? "CaregiverHome" : "PatientHome",
                      },
                    ],
                  });
                }}
              />
            )}
          </Stack.Screen>

          <Stack.Screen name="CaregiverHome">
            {(props) => (
              <CaregiverHomeScreen
                {...props}
                user={initialUser || {}}
                onLogout={makeLogout(props.navigation)}
                onEditContext={(patient) =>
                  props.navigation.navigate("PatientContext", { patient })
                }
                onOpenSettings={() =>
                  props.navigation.navigate("Settings", {
                    user: initialUser,
                    onLogout: makeLogout(props.navigation),
                  })
                }
              />
            )}
          </Stack.Screen>

          <Stack.Screen name="PatientContext">
            {(props) => (
              <PatientContextScreen
                {...props}
                patient={props.route.params?.patient}
                onBack={() => {
                  if (props.navigation.canGoBack()) {
                    props.navigation.goBack();
                  } else {
                    props.navigation.navigate("CaregiverHome");
                  }
                }}
              />
            )}
          </Stack.Screen>

          <Stack.Screen name="PatientHome">
            {(props) => (
              <PatientHomeScreen
                {...props}
                user={initialUser || {}}
                onLogout={makeLogout(props.navigation)}
                onOpenSettings={() =>
                  props.navigation.navigate("Settings", {
                    user: initialUser,
                    onLogout: makeLogout(props.navigation),
                  })
                }
              />
            )}
          </Stack.Screen>

          <Stack.Screen name="Settings" component={SettingsScreen} />
        </Stack.Navigator>
      </NavigationContainer>
    </>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#F5F7FA",
  },
});
