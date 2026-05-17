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
import * as Notifications from "expo-notifications";
import { NavigationContainer, createNavigationContainerRef } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { getCurrentUser, setToken, setUnauthorizedHandler } from "./src/services/api";
import { loadSession, saveSession, clearSession } from "./src/services/session";

import LoginScreen from "./src/screens/LoginScreen";
import PatientHomeScreen from "./src/screens/PatientHomeScreen";
import CaregiverHomeScreen from "./src/screens/CaregiverHomeScreen";
import PatientContextScreen from "./src/screens/PatientContextScreen";
import SettingsScreen from "./src/screens/SettingsScreen";

const Stack = createNativeStackNavigator();
const navigationRef = createNavigationContainerRef();

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export default function App() {
  const [booted, setBooted] = useState(false);
  const [initialUser, setInitialUser] = useState(null);

  const logoutToLogin = useCallback(async (navigation) => {
    await clearSession();
    setInitialUser(null);
    const nav = navigationRef.isReady() ? navigationRef : navigation;
    nav?.reset?.({ index: 0, routes: [{ name: "Login" }] });
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => logoutToLogin());
    return () => setUnauthorizedHandler(null);
  }, [logoutToLogin]);

  useEffect(() => {
    let mounted = true;
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
          if (mounted) setInitialUser(user);
        } catch (e) {
          if (e?.status === 401) {
            await clearSession();
            user = null;
          } else {
            console.warn("Could not refresh stored session user:", e?.message || e);
            if (mounted) setInitialUser(user);
          }
        }
      }
      if (mounted) setBooted(true);
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const makeLogout = useCallback((navigation) => async () => {
    await logoutToLogin(navigation);
  }, [logoutToLogin]);

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
      <NavigationContainer ref={navigationRef}>
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
                  props.navigation.navigate("Settings")
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
                  props.navigation.navigate("Settings")
                }
              />
            )}
          </Stack.Screen>

          <Stack.Screen name="Settings">
            {(props) => (
              <SettingsScreen
                {...props}
                user={initialUser}
                onLogout={makeLogout(props.navigation)}
              />
            )}
          </Stack.Screen>
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
