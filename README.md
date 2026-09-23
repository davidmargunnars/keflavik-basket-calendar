# Keflavík – Bónus deild karla calendar

Sjálfvirkt Apple Calendar/iCal feed fyrir leiki Keflavíkur karla í Bónus deildinni.

GitHub Actions keyrir á 6 klst. fresti og uppfærir `keflavik-basket.ics` út frá leikjadagskrá Sofascore. Sama event-ID er notað fyrir hvern leik svo breyttir leiktímar eiga að uppfærast í stað þess að búa til tvítekningu.

## Apple Calendar subscription
Eftir að fyrsta workflow-keyrslan hefur búið til ICS skrána má subscribe-a að raw slóð hennar í Apple Calendar.
